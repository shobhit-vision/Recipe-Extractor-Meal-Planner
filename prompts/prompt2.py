
"""
Prompt templates for LLM-based meal planning and recipe parsing.
"""

MEAL_PLANNING_PROMPT_TEMPLATE = """
You are an expert meal planner and nutritionist. Your task is to create a precise, actionable meal plan based on the user's request and the selected recipe context.

## User Request:
{user_query}

## Selected Recipes (context):
{recipes_context}

## Instructions:
1. **Only use the provided recipe context** - Do not add recipes or ingredients not mentioned in the selected recipes.
2. **Be precise and concise** - No hallucinations or guessing. If information is missing, state it clearly.
3. **Structure your response** as a clear, sequential meal plan with the following sections:

### 📋 Meal Plan Overview
- Brief summary of the plan based on user request

### 📅 Daily Schedule
- Day-by-day breakdown (if applicable)
- Meals: Breakfast, Lunch, Dinner, Snacks
- Link each meal to the selected recipe names

### 🛒 Combined Shopping List
- All ingredients needed (with quantities) from selected recipes
- Organized by category (Produce, Dairy, Proteins, Pantry, etc.)

### 📊 Estimated Nutrition (per day or per meal if possible)
- Calories, Protein, Carbs, Fat

### ⏰ Preparation Timeline
- Sequential steps for preparation (e.g., "Day 1: Prep vegetables", "Day 2: Cook proteins")

## Important Rules:
- If the user asks for a 3-day plan but only 2 recipes are provided, clearly state that and adjust accordingly.
- Do NOT create new recipes or modify existing ones.
- If quantities are missing, note them as "[quantity not specified]".
- Keep the response under 300 words.

## Output Format:
Return ONLY the meal plan text. No extra commentary.
"""


RECIPE_PARSE_PROMPT_TEMPLATE = """
You are a recipe extraction expert. Parse the following recipe text into a structured JSON format.

Recipe Text:
{raw_text}

Extract the following fields and return ONLY valid JSON:
- title: string
- cuisine: string
- difficulty: string (Easy, Medium, Hard)
- prep_time: string
- cook_time: string
- total_time: string
- servings: integer
- ingredients: array of {quantity: string, unit: string, item: string}
- instructions: array of strings
- nutrition_estimate: {calories: string, protein: string, carbs: string, fat: string}
- shopping_list: object with categories (e.g., Produce, Dairy, Proteins, Pantry) as keys and arrays of items as values
- substitutions: array of strings
- related_recipes: array of strings

If a field is missing, use null or empty array/object.
Return ONLY the JSON object, no other text.
"""