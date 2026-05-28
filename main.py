
#Initializing Dependencies
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

# ---------- NEW: import the LLM parser ----------
from llm import (
    get_llm,
    parse_recipe_text,  # <-- added
)
from scraper import fetch_html_camoufox, scrape_recipe

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"
if not env_path.exists():
    env_path = BASE_DIR / ".env.example"
load_dotenv(env_path)

app = FastAPI(
    title=os.getenv("APP_NAME", os.getenv("API_TITLE", "Recipe extractor & Meal Planner")),
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent

initialize_database()

# ---------- Pydantic model for incoming request ----------
class SaveRecipeRequest(BaseModel):
    recipe: dict   # The whole structured recipe JSON


class ScrapeRequest(BaseModel):
    url: str

class ScrapeResponse(BaseModel):
    success: bool
    data: Optional[str] = None
    error: Optional[str] = None


class ParseRequest(BaseModel):
    raw_text: str


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


async def llm_status():
    llm, error = get_llm()
    if llm:
        return {"available": True, "error": None, "model": "llama-3.3-70b-versatile"}
    else:
        return {"available": False, "error": error, "model": None}
    
async def health_check():
    return {"status": "healthy", "service": "recipe-scraper", "version": "1.0.0"}


# ---------- Extract raw text (for frontend) ----------
@app.post("/extract-raw")
async def extract_raw(request: ScrapeRequest):
    """Extract raw visible text from a URL (same as scraping but returns extra stats)."""
    if not request.url:
        raise HTTPException(status_code=400, detail="URL is required")
    if not request.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    try:
        # Reuse existing scraper – returns the raw text
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- AI‑parse endpoint(LLM Based) ----------
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


# ---------- Save recipe to Supabase----------
@app.post("/save-recipe")
async def save_recipe(request: SaveRecipeRequest):
    """Save the structured recipe via Supabase."""
    recipe_data = request.recipe   # this is a dict
    new_row = {"recipe_data": recipe_data}

    try:
        # Supabase insert – returns APIResponse with .data (list of rows)
        result = supabase_client.table("recipe").insert(new_row).execute()

        # Check for errors from Supabase
        if hasattr(result, 'error') and result.error:
            raise HTTPException(status_code=500, detail=str(result.error))

        # Extract the id of the newly inserted row
        inserted_id = result.data[0]["id"]
        return {"id": inserted_id, "message": "Recipe saved successfully"}

    except HTTPException:
        raise  # re-raise our own HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Extract recipes from Supabase----------
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

# ---------- Existing endpoints ----------
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
        }
    }


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