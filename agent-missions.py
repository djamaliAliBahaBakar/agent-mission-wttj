import http.client
import sys

from xpoz import XpozClient
from dotenv import load_dotenv
import os
from langgraph.graph import START, END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

import json

from dictionary import AgentMissionsState
from pathlib import Path
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from json import JSONDecodeError
import asyncio

from prompts import SYSTEM_PROMPT,  USER_PROMPT_FILTER
from tools import get_profile, client, update_mission, mark_mission_error
from mission_graph import start
from supabase import create_client, Client
import logging
from tenacity import retry, stop_after_attempt, wait_fixed


async def run():

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)


    sys.path.append(str(Path(__file__).parent.parent.parent))
    from shared.utils import parse_json_response

    # Chemin absolu vers .env à la racine du projet
    dotenv_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(dotenv_path=dotenv_path)
    url= os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase = create_client(url, key)
 
    @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def scraper(state : AgentMissionsState):
        """ Collect missions from default source
            here WTTJ (Welcome to the jungle)
        """
        queries = state["queries"]
        try:
            conn = http.client.HTTPSConnection("api.apify.com")
            payload = json.dumps({
                "queries": queries
            })
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': f"Bearer {os.environ['APIFY_API_KEY']}"
            }
            url = f"/v2/acts/{os.environ['APIFY_ACTOR_ID']}/run-sync-get-dataset-items"
            conn.request("POST", url, payload, headers)

            res = conn.getresponse()
            if res.status != 200 and res.status != 201:
                raise RuntimeError(f"Apify HTTP error: {res.status}")
             
            data = res.read()
            try:
                ret = json.loads(data.decode("utf-8"))
                if not ret:
                    raise RuntimeError(f"Apify JSON error : empty ")
            except json.JSONDecodeError as e:
                raise RuntimeError("Invalid JSON from Apify") from e

            if not isinstance(ret, list):
                raise RuntimeError("Unexpected response format from Apify")
            return {"missions_to_process": ret}
        except Exception as e:
            logging.error(f"[SCRAPER] Error calling Apify: {str(e)}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(10))
    def deduplicate(state : AgentMissionsState):
        missions = state["missions_to_process"]
        updated_mission=[]
        for mission in missions:
            url = mission.get("url")
            name = mission.get("name")
            source="wttj"
            status="new"
            if not name:
                logging.error(f"[DEDUPLICATE] Mission url {url}  with empty name")
                continue
            if not url:
                 logging.error(f"[DEDUPLICATE] Mission {name}  with empty url")
                 continue


            try:
                response = (
                    supabase.table("missions")
                    .select("*")
                    .eq("url", url)
                    .execute()
                )
                data = response.data

                if len(data) == 0:
                    updated_mission.append(mission)

                    inserted = (
                        supabase.table("missions")
                        .insert({"url": url, "name": name, "source": source, "status": status})
                        .execute()
                    )

                else:
                    existing_mission= data[0]
                    retry_count= existing_mission["retry_count"]
                    if retry_count is None:
                        retry_count = 0
                    if existing_mission["status"] == "error" and retry_count < 3:
                        updated_mission.append(mission)

                        updated = (
                                supabase.table("missions")
                                .update({"retry_count": retry_count + 1})
                                .eq("url", url)
                                .execute()
                            )

                    else:
                        logging.info(f"[DEDUPLICATE] Mission {name}  ignored")
            except Exception as e:
                logging.error(f"[DEDUPLICATE] Error calling supabase: {str(e)}")
                raise
        return {"missions_to_process": updated_mission}


    def create_dict_mission_by_url(missions):
        dict_missions = {}
        for mission in missions:
            #print(f" create_dict_mission_by_slug {mission}")
            url = mission.get('url')
            if url is not None:
                dict_missions[url] = mission
        return dict_missions

    @retry(reraise=True, stop=stop_after_attempt(3))
    def process_llm_batch(batch, profile, missions_by_url, mission_evaluations):
        try:
            user_msg = USER_PROMPT_FILTER.format(missions=json.dumps(batch, indent=2),profile=json.dumps(profile, indent=2))
            try:
                response = client.messages.create(
                        model="claude-haiku-4-5-20251001",  # ← Haiku 4.5
                        max_tokens=1024,
                        system=SYSTEM_PROMPT,
                        messages=[ {"role": "user", "content": user_msg}]
                )  
            except:
                raise RuntimeError("llm_filter_failed")
            
            try:
                text = response.content[0].text
            except:
                raise RuntimeError("llm_empty_response")
            try:
                json_text = parse_json_response(text)
            except:
                raise RuntimeError("json_parse_failed")
            
            for one_json in json_text:
                eligible_mission = {}
                if not isinstance(one_json, dict):
                    continue
                url = one_json.get("url")
                eligible = one_json.get("eligible")
                justification = one_json.get("justification")

                if url is None or not isinstance(url, str) or url.strip() == "":
                    continue

                if eligible is None or not isinstance(eligible, bool):
                    continue
                if justification is None or not isinstance(justification, str) or justification.strip() == "":
                    continue
                mission = missions_by_url.get(url) 
                if mission is not None and eligible  == True:
                    if len(mission_evaluations) < 5:
                        eligible_mission["mission"]  = mission
                        eligible_mission["eligible"]  = eligible
                        eligible_mission["justification"]  = justification
                        mission_evaluations.append(eligible_mission)
                        update_mission(url, "eligible")
                elif mission is not None:
                    update_mission(url, "filtered_out")
                else:
                    continue
            # Traiter les missions non récupérées par le llm
            batch_urls = set(m["url"] for m in batch if m.get("url"))
            returned_urls = set(one_json.get("url") for one_json in json_text if one_json.get("url"))
            missing_urls = batch_urls - returned_urls
            for url in missing_urls:
                mark_mission_error(url, "llm_missing_url")
        except Exception as e:
            logging.error(f"[FILTER] An error occurred during llm : {e}")
            raise
    
    def mark_batch_error(batch,reason):
        for mission in batch:
            try:
                url = mission.get("url")
                if not url:
                    logging.warning(f"Url not available")
                    continue
                if len(reason) > 35:
                    reason = reason[:35]
                updated = (
                supabase.table("missions")
                .update({"status": "error", "error_reason": reason})
                .eq("url", url)
                .execute())
            except Exception as e:
                logging.critical(f"An error occurred during mark batch error : {e}")
                raise
            


    def filter(state : AgentMissionsState):
        missions = state["missions_to_process"]
        profile  = get_profile()
        missions_by_url = create_dict_mission_by_url(missions)
        mission_evaluations = []
        batch_size = 3
        for i in range(0, len(missions), batch_size):
            batch = missions[ i: i+batch_size]
            try:
                process_llm_batch(batch, profile, missions_by_url, mission_evaluations)
            except Exception as e:
                reason = str(e)
                mark_batch_error(batch, reason) 
                
        return {"filtered_missions": mission_evaluations}

 

    async def orchestrator(state: AgentMissionsState):
        missions = state.get("filtered_missions",[])
        async with AsyncPostgresSaver.from_conn_string(os.environ["SUPABASE_DATABASE_URL"]) as checkpointerPostGre:
            await checkpointerPostGre.setup()
            graph_mission = start(checkpointerPostGre)
            for mission in missions:
                thread_id = mission["mission"]["url"]
                config_mission = {"configurable": {"thread_id": thread_id}}
                await graph_mission.ainvoke({"mission": mission["mission"], "thread_id": thread_id},config=config_mission)
        return {}


    builder = StateGraph(AgentMissionsState)
    builder.add_node("scraper",scraper)
    builder.add_node("deduplicate", deduplicate)
    builder.add_node("filter", filter)
    builder.add_node("orchestrator", orchestrator)
    builder.add_edge(START, "scraper")
    builder.add_edge("scraper", "deduplicate")
    builder.add_edge("deduplicate", "filter")
    builder.add_edge("filter", "orchestrator")
    builder.add_edge("orchestrator", END)

    memory = MemorySaver()
    graph = builder.compile(checkpointer=memory)

    result = await graph.ainvoke(
        {
            "queries": ["IA", "Agent IA"],
        },
        config={"configurable": {"thread_id": "test-1"}}
    )


asyncio.run(run())