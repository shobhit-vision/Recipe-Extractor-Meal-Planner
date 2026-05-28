
import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
import json
import re
from prompts.prompt import RECIPE_PARSE_TEMPLATE


load_dotenv() #loading env variable 

_llm_instance = None
_initialisation_error = None

def get_llm():# initializing groq llm
    
    global _llm_instance, _initialisation_error

    if _llm_instance is not None:
        return _llm_instance, None

    # If we already attempted and failed, return cached error
    if _initialisation_error is not None:
        return None, _initialisation_error

    # Attempt to initialise
    try:
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable is not set. "
                             "Please set it in a .env file or export it.")

        _llm_instance = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=groq_api_key,
            temperature=0
        )
        return _llm_instance, None

    except Exception as e:
        _initialisation_error = str(e)
        return None, _initialisation_error


def parse_recipe_text(raw_text: str) -> dict: # llm based pasing function
   
    llm, error = get_llm()
    if error or llm is None:
        raise RuntimeError(f"LLM not available: {error}")

    prompt = ChatPromptTemplate.from_template(RECIPE_PARSE_TEMPLATE)
    chain = prompt | llm

    try:
        response = chain.invoke({"raw_text": raw_text})
        json_str = response.content if hasattr(response, 'content') else str(response)

        # Clean up possible markdown fences
        json_str = re.sub(r'^```(?:json)?\s*', '', json_str.strip())
        json_str = re.sub(r'\s*```$', '', json_str)

        parsed = json.loads(json_str)

        # validation to ensure required keys exist

        required_keys = [
            "title", "cuisine", "prep_time", "cook_time", "total_time",
            "servings", "difficulty", "ingredients", "instructions",
            "nutrition_estimate", "substitutions", "shopping_list", "related_recipes"
        ]
        for key in required_keys:
            if key not in parsed:
                parsed[key] = None   

        return parsed

    except Exception as e:
        raise ValueError(f"Failed to parse LLM output: {e}") from e