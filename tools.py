import os
import json

import anthropic
import sys
from dotenv import load_dotenv
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))
from supabase import create_client
import logging

# Chemin absolu vers .env à la racine du projet
dotenv_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

url= os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

def get_profile():
    base_dir = os.path.dirname(__file__)
    file_path = os.path.join(base_dir, 'profile.json')
    with open(file_path) as file:
        return json.load(file)

def update_mission(url, status):
    try:
        if url is not None:
            updated = (
            supabase.table("missions")
            .update({"status": status})
            .eq("url", url)
            .execute())
    except Exception as e:
        logging.error(f"An error occurred during update_mission: {e}")
        raise


def mark_mission_error(url,reason):
    try:
        if url is not None:
            updated = (
            supabase.table("missions")
            .update({"status": "error", "error_reason": reason})
            .eq("url", url)
            .execute())
    except Exception as e:
        logging.critical(f"An error occurred during mark batch error : {e}")
        raise