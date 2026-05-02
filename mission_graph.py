import os
import resend
import json
from dictionary import MissionState
from tools import get_profile
from prompts import PROMPT_DRAFT_GENERATOR
from langgraph.types import interrupt
from tools import client, update_mission, mark_mission_error
from langgraph.graph import START, END, StateGraph
import sys
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import quote
from langgraph.types import Command
from supabase import create_client, Client
import logging
from tenacity import retry, stop_after_attempt, wait_fixed


sys.path.append(str(Path(__file__).parent.parent.parent))
from shared.utils import parse_json_response

# Chemin absolu vers .env à la racine du projet
dotenv_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

graph_mission = None

def generateDraft(state : MissionState):
    
    mission = state["mission"]
    url = mission.get("url")
    profile = get_profile()
    candidate_name = profile.get("candidate_name")
    user_msg = PROMPT_DRAFT_GENERATOR.format(mission=json.dumps(mission, indent=2),profile=json.dumps(profile, indent=2), candidate_name=candidate_name)
    try:
        response = client.messages.create(
                model="claude-haiku-4-5-20251001",  # ← Haiku 4.5
                max_tokens=1024,
                messages=[ {"role": "user", "content": user_msg}]
        )
        text = response.content[0].text
        #print(f"Mission  : {mission}")
        #print(f"Generator text : {text}")
        candidate = text

        return {"candidate" : candidate, "counter": 0}
    except Exception as e:
        logging.error(f"[DRAFT] LLM generation failed : {e}")
        mark_mission_error(url, "llm_generation_failed")
        raise

def sendEmail(state: MissionState):
    candidate = state["candidate"]
    mission_name= state["mission"]["name"]
    url = state["mission"]["url"]
    # Envoyer l'email via resend
    thread_id = state["mission"]["url"]
    encoded_thread_id = quote(thread_id, safe="")
    base_url = os.environ["FASTAPI_URL"]
    validate_status = state.get("validate_status")

    subject = f"Candidature à valider - [{mission_name}]"
    if validate_status == "no_change":
        subject = f"!!ATTENTION!! Pas de changement constaté - Candidature  - [{mission_name}]"
    elif validate_status == "invalid":
        subject = f"Candidature non valide - A confirmer - Candidature  - [{mission_name}]"
    else:
        subject = f"Candidature à valider - [{mission_name}]"

    liens = f"""
    ---
    ✅ Approuver : {base_url}/approve?thread_id={encoded_thread_id}
    ❌ Rejeter   : {base_url}/reject?thread_id={encoded_thread_id}
    ✏️ Modifier  : {base_url}/modify?thread_id={encoded_thread_id}
    """

    resend.api_key = os.environ["RESEND_API_KEY"]
    params = {
        "from": os.environ["EMAIL_MISSION_FROM"],
        "to": os.environ["EMAIL_MISSION_TO"],
        "subject": subject,
        "text": candidate + liens
    }
    try:
        resend.Emails.send(params)
        update_mission(url, "email_sent")
        return {"email_sent": True}
    except Exception as e:
        logging.error(f"[EMAIL] An error occurred during  email : {e}")
        mark_mission_error(url, "email_rejected")
        return Command(
            goto = END
        )

def waitForDecision(state: MissionState):
    candidate = state["candidate"]
    mission_name= state["mission"]["name"]
    validate_status = state.get("validate_status")
    question =""
    if validate_status == "ok" or validate_status is None:
        question = "Que souhaitez-vous faire avec cette candidature ?"
    elif validate_status == "no_change":
        question = "Pouvez-vous mettre à jour la candidature ?"
    else:
        question = "Candidature non valide. Vous confirmez ?"



    decision = interrupt({
        "question": question,
        "mission": mission_name,
        "candidate": candidate
    })

    return {"decision": decision}

def validate(state: MissionState):
    new_candidate = state["updated_candidate"]
    current_candidate = state["candidate"]

    counter = state["counter"]
    if new_candidate is not None and new_candidate != current_candidate:
        return Command(
                update={"candidate":new_candidate, "counter": counter + 1, "validate_status": "ok"},
                goto = "sendEmail"
            )
    elif new_candidate == current_candidate:
        return Command(
            update={"validate_status":"no_change", "counter": counter + 1},
            goto = "sendEmail"
        )
    else:
        return Command(
            update={"validate_status":"invalid", "counter": counter + 1},
            goto = "sendEmail"
        )


def router(state: MissionState):
    decision = state["decision"]
    counter = state["counter"]
    url = state["mission"]["url"]
    if decision is None or  decision.get("action") is None:
        return {}
    
    if decision.get("action") == "approve":
        update_mission(url, "approved")
        return Command(
            goto = "reporter"
        )
    elif decision.get("action") == "reject":
        update_mission(url, "rejected")
        return Command(
            goto = END
        )
        
    elif decision.get("action") == "modify":
        new_candidate = state["decision"].get("updated_candidate")
        if counter < 3:
            return Command(
                update={"updated_candidate":new_candidate},
                goto = "validate"
            )
        else:
            mark_mission_error(url, "limit_reached")
            return Command(
                goto = "reporter"
            )
    else:
         return Command(
            goto = END
        )

def reporter(state:MissionState):
    candidate = state["candidate"]
    if candidate is None:
        return {}
    mission_name= state["mission"]["name"]

    url = state["mission"]["url"]

    liens = f"""
    ---
    ✅ URL : {url}
    """

    resend.api_key = os.environ["RESEND_API_KEY"]
    params = {
        "from": os.environ["EMAIL_MISSION_FROM"],
        "to": os.environ["EMAIL_MISSION_TO"],
        "subject": f"✅ Candidature approuvée - [{mission_name}]",
        "text": candidate + liens
    }
    try:
        resend.Emails.send(params)
    except Exception as e:
        logging.error(f"[REPORTER] An error occurred  : {e}")
        mark_mission_error(url, "send_email_failed")
    return {}

def start(checkpointerPostGre):
    builder_mission = StateGraph(MissionState)
    builder_mission.add_node("generateDraft",generateDraft)
    builder_mission.add_node("waitForDecision",waitForDecision)
    builder_mission.add_node("sendEmail",sendEmail)
    builder_mission.add_node("router",router)
    builder_mission.add_node("reporter",reporter)
    builder_mission.add_node("validate",validate)

    builder_mission.add_edge(START, "generateDraft")
    builder_mission.add_edge("generateDraft", "sendEmail")
    builder_mission.add_edge("sendEmail", "waitForDecision")
    builder_mission.add_edge("waitForDecision", "router")
    builder_mission.add_edge("reporter", END)
    graph_mission = builder_mission.compile(checkpointer=checkpointerPostGre)
    return graph_mission