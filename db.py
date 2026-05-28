import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

if not all([SUPABASE_URL, SUPABASE_KEY, DATABASE_URL]):
    raise Exception("Missing required environment variables: SUPABASE_URL, SUPABASE_KEY, DATABASE_URL")

# Supabase client instance (exported for use in main.py)
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_db_connection():
    """Create a new psycopg2 connection (used for direct SQL queries)."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def initialize_database():
    """Create the recipe table (with JSONB and timestamp) using psycopg2."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS recipe (
                    id BIGSERIAL PRIMARY KEY,
                    recipe_data JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            conn.commit()
    finally:
        conn.close()