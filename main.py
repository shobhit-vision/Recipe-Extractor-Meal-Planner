# main.py
import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from db import get_db_connection, initialize_database, supabase_client

# ---------- Import LLM parser ----------
from llm import get_llm, parse_recipe_text

# ---------- Import prompts ----------
from prompts.prompt2 import MEAL_PLANNING_PROMPT_TEMPLATE
from scraper import fetch_html_camoufox, scrape_recipe

# Define BASE_DIR once
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables
env_path = BASE_DIR / ".env"
if not env_path.exists():
    env_path = BASE_DIR / ".env.example"
load_dotenv(env_path)

# Initialize FastAPI app
app = FastAPI(
    title=os.getenv("APP_NAME", os.getenv("API_TITLE", "Recipe extractor & Meal Planner")),
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
initialize_database()

# ---------- Pydantic models ----------
class SaveRecipeRequest(BaseModel):
    recipe: dict

class ScrapeRequest(BaseModel):
    url: str

class ScrapeResponse(BaseModel):
    success: bool
    data: Optional[str] = None
    error: Optional[str] = None

class ParseRequest(BaseModel):
    raw_text: str

class MealPlanRequest(BaseModel):
    user_query: str
    recipe_ids: List[int]


# ---------- Helper: format recipes for context ----------
def format_recipes_for_context(recipes_data: List[dict]) -> str:
    """
    Convert a list of recipe dicts into a readable text context for the LLM.
    """
    context_parts = []
    for i, recipe in enumerate(recipes_data, 1):
        parts = []
        parts.append(f"=== RECIPE {i} ===")
        parts.append(f"Title: {recipe.get('title', 'Untitled')}")
        parts.append(f"Cuisine: {recipe.get('cuisine', 'Not specified')}")
        parts.append(f"Difficulty: {recipe.get('difficulty', 'Not specified')}")
        parts.append(f"Prep Time: {recipe.get('prep_time', 'Not specified')}")
        parts.append(f"Cook Time: {recipe.get('cook_time', 'Not specified')}")
        parts.append(f"Servings: {recipe.get('servings', 'Not specified')}")

        # Ingredients
        ingredients = recipe.get('ingredients', [])
        if ingredients:
            ingr_lines = []
            for ing in ingredients:
                qty = ing.get('quantity', '')
                unit = ing.get('unit', '')
                item = ing.get('item', '')
                ingr_lines.append(f"  - {qty} {unit} {item}".strip())
            parts.append("Ingredients:")
            parts.extend(ingr_lines)
        else:
            parts.append("Ingredients: None listed")

        # Instructions
        instructions = recipe.get('instructions', [])
        if instructions:
            parts.append("Instructions:")
            for idx, step in enumerate(instructions, 1):
                parts.append(f"  {idx}. {step}")
        else:
            parts.append("Instructions: None listed")

        # Nutrition
        nutrition = recipe.get('nutrition_estimate', {})
        if nutrition:
            parts.append(f"Nutrition (per serving):")
            parts.append(f"  Calories: {nutrition.get('calories', 'N/A')}")
            parts.append(f"  Protein: {nutrition.get('protein', 'N/A')}")
            parts.append(f"  Carbs: {nutrition.get('carbs', 'N/A')}")
            parts.append(f"  Fat: {nutrition.get('fat', 'N/A')}")

        # Shopping list
        shopping = recipe.get('shopping_list', {})
        if shopping:
            parts.append("Shopping List Categories:")
            for category, items in shopping.items():
                items_str = ", ".join(items) if items else "None"
                parts.append(f"  {category}: {items_str}")

        parts.append("")  # blank line between recipes
        context_parts.append("\n".join(parts))

    return "\n".join(context_parts)


# ---------- endpoints ----------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = BASE_DIR / "recipe_extractor.html"
    if not html_path.exists():
        return HTMLResponse(
            content="<h1>FastAPI Recipe Scraper</h1><p>recipe_extractor.html not found</p>",
            status_code=404
        )
    html = html_path.read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/status")
async def status():
    return {
        "status": "running",
        "version": "1.0.0",
        "service": "Recipe Scraper API",
        "endpoints": {
            "GET /": "Serve recipe_extractor.html",
            "POST /scrape": "Scrape single recipe",
            "GET /docs": "Swagger UI",
            "GET /redoc": "ReDoc",
            "POST /extract-raw": "Extract raw text from URL",
            "POST /ai-parse": "LLM parsing of raw text",
            "POST /save-recipe": "Save a structured recipe",
            "GET /recipes": "List saved recipes",
            "GET /recipes/{id}": "Get saved recipe details",
            "POST /meal-plan": "Generate a meal plan from selected recipes",
        }
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "recipe-scraper", "version": "1.0.0"}


# ---------- Extract raw text ----------
@app.post("/extract-raw")
async def extract_raw(request: ScrapeRequest):
    """Extract raw visible text from a URL."""
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required")
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    try:
        raw_text = await asyncio.wait_for(
            scrape_recipe(request.url, save_path="", save_html_path=None),
            timeout=90
        )
        if not raw_text:
            raise HTTPException(status_code=500, detail="No content extracted")
        return {
            "url": str(request.url),
            "raw_text": raw_text,
            "text_length": len(raw_text),
            "line_count": raw_text.count("\n") + 1
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Request timed out after 90 seconds")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- AI‑parse endpoint ----------
@app.post("/ai-parse")
async def ai_parse_recipe(request: ParseRequest):
    """Take raw text, run through the Groq LLM parser, return structured recipe."""
    if not request.raw_text.strip():
        raise HTTPException(status_code=400, detail="raw_text is empty")
    try:
        recipe = parse_recipe_text(request.raw_text)
        return {"success": True, "data": recipe}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Save recipe to Supabase ----------
@app.post("/save-recipe")
async def save_recipe(request: SaveRecipeRequest):
    """Save the structured recipe via Supabase."""
    recipe_data = request.recipe
    new_row = {"recipe_data": recipe_data}

    try:
        result = supabase_client.table("recipe").insert(new_row).execute()

        if hasattr(result, 'error') and result.error:
            raise HTTPException(status_code=500, detail=str(result.error))

        inserted_id = result.data[0]["id"]
        return {"id": inserted_id, "message": "Recipe saved successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Get all recipes ----------
@app.get("/recipes")
async def get_recipes():
    try:
        result = (
            supabase_client
            .table("recipe")
            .select("id, recipe_data, Date")
            .execute()
        )

        recipes = result.data or []
        formatted = []

        for recipe in recipes:
            recipe_data = recipe.get("recipe_data") or {}

            formatted.append({
                "id": recipe.get("id"),
                "title": recipe_data.get("title"),
                "cuisine": recipe_data.get("cuisine"),
                "difficulty": recipe_data.get("difficulty"),
                "date_extracted": recipe.get("Date") or {}
            })

        return formatted

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Get single recipe ----------
@app.get("/recipes/{recipe_id}")
async def get_recipe_by_id(recipe_id: int):
    try:
        res = (
            supabase_client
            .table("recipe")
            .select("id, recipe_data")
            .eq("id", recipe_id)
            .single()
            .execute()
        )

        row = res.data
        if not row:
            raise HTTPException(status_code=404, detail="Recipe not found")

        return row.get("recipe_data") or {}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- MEAL PLAN ENDPOINT ----------
@app.post("/meal-plan")
async def generate_meal_plan(request: MealPlanRequest):
    """
    Generate a meal plan based on user query and up to 3 selected recipes.
    """
    # Validate: max 3 recipes
    if len(request.recipe_ids) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 recipes can be selected for planning")
    
    if len(request.recipe_ids) == 0:
        raise HTTPException(status_code=400, detail="At least 1 recipe must be selected")

    if not request.user_query or not request.user_query.strip():
        raise HTTPException(status_code=400, detail="User query cannot be empty")

    # Fetch the selected recipes from Supabase
    recipes_data = []
    for recipe_id in request.recipe_ids:
        try:
            res = (
                supabase_client
                .table("recipe")
                .select("id, recipe_data")
                .eq("id", recipe_id)
                .single()
                .execute()
            )
            row = res.data
            if row:
                recipe_data = row.get("recipe_data", {})
                recipe_data["id"] = row.get("id")
                recipes_data.append(recipe_data)
            else:
                raise HTTPException(status_code=404, detail=f"Recipe with ID {recipe_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching recipe {recipe_id}: {str(e)}")

    # Format recipes as context
    recipes_context = format_recipes_for_context(recipes_data)

    # Build the prompt
    prompt = MEAL_PLANNING_PROMPT_TEMPLATE.format(
        user_query=request.user_query,
        recipes_context=recipes_context
    )

    # Get LLM and generate response
    llm, error = get_llm()
    if not llm:
        raise HTTPException(status_code=503, detail=f"LLM service unavailable: {error}")

    try:
        response = llm.invoke(prompt)
        plan_text = response.content if hasattr(response, 'content') else str(response)

        # Clean up any markdown code fences
        if plan_text.startswith("```"):
            lines = plan_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            plan_text = "\n".join(lines)

        return {
            "success": True,
            "plan": plan_text,
            "recipes_used": [r.get("title", f"Recipe {i+1}") for i, r in enumerate(recipes_data)],
            "recipe_ids": request.recipe_ids
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM generation failed: {str(e)}")


# ---------- Exception handlers ----------
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "data": None, "error": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    print(f"❌ Unhandled: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "data": None, "error": "Internal server error"},
    )


@app.on_event("startup")
async def startup_event():
    print("🟢 FastAPI application started")
    print(f"📚 Service: {os.getenv('APP_NAME', 'FastAPI Demo')}")


@app.on_event("shutdown")
async def shutdown_event():
    print("🔴 FastAPI application shutting down")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"🚀 Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info", workers=1)