import json
import os
import re
import warnings
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from prompts.prompt import RECIPE_PARSE_TEMPLATE

load_dotenv()  # loading env variable

_llm_instance = None
_initialisation_error = None
_user_provided_key = None
_groq_api_error_codes = {
    'invalid_api_key': 'Invalid API key',
    'rate_limit_exceeded': 'Rate limit exceeded',
    'insufficient_quota': 'Insufficient quota or token limit exhausted',
    'billing_hard_limit_reached': 'Billing hard limit reached',
    'token_limit_exceeded': 'Token limit exceeded'
}

def set_user_groq_key(api_key: str) -> Tuple[bool, str]:
    """
    Set a user-provided Groq API key when the default key is exhausted.
    
    Args:
        api_key: User's Groq API key
        
    Returns:
        Tuple of (success, message)
    """
    global _user_provided_key, _llm_instance, _initialisation_error
    
    if not api_key or not api_key.strip():
        return False, "API key cannot be empty"
    
    # Basic validation - Groq keys typically start with "gsk_"
    api_key = api_key.strip()
    if not api_key.startswith("gsk_"):
        return False, "Invalid Groq API key format. Keys should start with 'gsk_'"
    
    # Test the key by attempting to create a temporary LLM instance
    try:
        test_llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=api_key,
            temperature=0
        )
        # Try a simple invoke to verify the key works
        test_response = test_llm.invoke("test")
        
        # If successful, update the global key and reset instances
        _user_provided_key = api_key
        _llm_instance = test_llm  # Use the tested instance
        _initialisation_error = None
        
        return True, "Groq API key validated and set successfully!"
        
    except Exception as e:
        error_msg = str(e).lower()
        if "invalid" in error_msg or "unauthorized" in error_msg:
            return False, "Invalid API key. Please check your Groq API key and try again."
        elif "rate" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
            return False, "This API key has also exceeded its limits. Please use a different key."
        else:
            return False, f"Failed to validate API key: {str(e)}"

def get_current_api_key() -> Optional[str]:
    """
    Get the current active API key (user-provided or from env).
    """
    if _user_provided_key:
        return _user_provided_key
    return os.getenv("GROQ_API_KEY")

def reset_to_env_key():
    """
    Reset to using the environment variable API key.
    """
    global _user_provided_key, _llm_instance, _initialisation_error
    _user_provided_key = None
    _llm_instance = None
    _initialisation_error = None

def is_using_user_key() -> bool:
    """
    Check if currently using a user-provided key.
    """
    return _user_provided_key is not None

def check_groq_error_type(error: Exception) -> str:
    """
    Analyze the error to determine what kind of Groq API error occurred.
    
    Returns:
        Error category string
    """
    error_str = str(error).lower()
    
    if "insufficient_quota" in error_str or "quota" in error_str:
        return "insufficient_quota"
    elif "rate_limit" in error_str or "rate" in error_str:
        return "rate_limit_exceeded"
    elif "invalid" in error_str or "unauthorized" in error_str or "authentication" in error_str:
        return "invalid_api_key"
    elif "billing" in error_str:
        return "billing_hard_limit_reached"
    elif "token" in error_str:
        return "token_limit_exceeded"
    else:
        return "unknown_error"

def is_token_exhausted_error(error: Exception) -> bool:
    """
    Check if the error is related to token exhaustion or quota limits.
    """
    error_type = check_groq_error_type(error)
    return error_type in ["insufficient_quota", "rate_limit_exceeded", 
                         "billing_hard_limit_reached", "token_limit_exceeded"]

def get_groq_signup_url() -> str:
    """
    Get the URL for Groq console to create API keys.
    """
    return "https://console.groq.com/keys"

def get_llm():
    """
    Initializing Groq LLM with support for user-provided API keys.
    
    Returns:
        Tuple of (llm_instance or None, error_message or None)
    """
    global _llm_instance, _initialisation_error, _user_provided_key

    if _llm_instance is not None:
        return _llm_instance, None

    # If we already attempted and failed, return cached error
    if _initialisation_error is not None:
        # Check if it's a token exhaustion error
        if is_token_exhausted_error(Exception(_initialisation_error)):
            return None, {
                "error": _initialisation_error,
                "needs_key": True,
                "groq_url": get_groq_signup_url()
            }
        return None, _initialisation_error

    # Attempt to initialize
    try:
        api_key = get_current_api_key()
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY environment variable is not set. "
                "Please set it in a .env file or export it."
            )

        _llm_instance = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=api_key,
            temperature=0
        )
        
        # Test the connection
        try:
            test_response = _llm_instance.invoke("test")
        except Exception as test_error:
            _initialisation_error = str(test_error)
            _llm_instance = None
            
            if is_token_exhausted_error(test_error):
                return None, {
                    "error": f"Groq API quota exhausted: {str(test_error)}",
                    "needs_key": True,
                    "groq_url": get_groq_signup_url()
                }
            raise test_error
            
        return _llm_instance, None

    except Exception as e:
        _initialisation_error = str(e)
        if is_token_exhausted_error(e):
            return None, {
                "error": str(e),
                "needs_key": True,
                "groq_url": get_groq_signup_url()
            }
        return None, str(e)


def parse_recipe_text(raw_text: str) -> dict:
    """
    LLM-based parsing function with support for user-provided API keys.
    
    Args:
        raw_text: Raw recipe text to parse
        
    Returns:
        Parsed recipe dictionary
        
    Raises:
        RuntimeError: If LLM is not available or token limits are exceeded
        ValueError: If parsing fails
    """
    llm_result = get_llm()
    
    if isinstance(llm_result[1], dict) and llm_result[1].get("needs_key"):
        # Token exhaustion - need user to provide API key
        error_info = llm_result[1]
        raise RuntimeError(json.dumps({
            "error": error_info["error"],
            "needs_key": True,
            "groq_url": error_info["groq_url"],
            "message": "Groq API token limit exhausted. Please provide your own Groq API key to continue."
        }))
    elif llm_result[1]:
        raise RuntimeError(f"LLM not available: {llm_result[1]}")
    
    llm = llm_result[0]
    if llm is None:
        raise RuntimeError("LLM not available")

    prompt = ChatPromptTemplate.from_template(RECIPE_PARSE_TEMPLATE)
    chain = prompt | llm

    try:
        response = chain.invoke({"raw_text": raw_text})
        json_str = response.content if hasattr(response, 'content') else str(response)

        # Clean up possible markdown fences
        json_str = re.sub(r'^```(?:json)?\s*', '', json_str.strip())
        json_str = re.sub(r'\s*```$', '', json_str)

        parsed = json.loads(json_str)

        # Validation to ensure required keys exist
        required_keys = [
            "title", "cuisine", "prep_time", "cook_time", "total_time",
            "servings", "difficulty", "ingredients", "instructions",
            "nutrition_estimate", "substitutions", "shopping_list", "related_recipes"
        ]
        for key in required_keys:
            if key not in parsed:
                parsed[key] = None

        return parsed

    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM output as JSON: {e}")
    except Exception as e:
        # Check if this is a token exhaustion error during invocation
        if is_token_exhausted_error(e):
            raise RuntimeError(json.dumps({
                "error": str(e),
                "needs_key": True,
                "groq_url": get_groq_signup_url(),
                "message": "Groq API token limit exhausted. Please provide your own Groq API key to continue."
            }))
        raise ValueError(f"Failed to parse LLM output: {e}") from e


# Utility function to get API key status
def get_api_key_status() -> dict:
    """
    Get the current status of the Groq API key configuration.
    
    Returns:
        Dictionary with status information
    """
    return {
        "using_user_key": is_using_user_key(),
        "has_env_key": bool(os.getenv("GROQ_API_KEY")),
        "current_key_prefix": get_current_api_key()[:10] + "..." if get_current_api_key() else None,
        "llm_initialized": _llm_instance is not None,
        "error": _initialisation_error
    }