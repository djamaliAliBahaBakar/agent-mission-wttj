from fastapi import FastAPI, Form
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from mission_graph import start
from langgraph.types import Command
import os
from fastapi.templating import Jinja2Templates

app = FastAPI()

from fastapi import Request
from fastapi.responses import HTMLResponse

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))






async def executeGraph(action, thread_id):
    async with AsyncPostgresSaver.from_conn_string(os.environ["SUPABASE_DATABASE_URL"]) as checkpointerPostGre:
        await checkpointerPostGre.setup()
        graph_mission = start(checkpointerPostGre)
        config_mission = {"configurable": {"thread_id": thread_id}}
        await graph_mission.ainvoke(Command(resume={"action":action}),config=config_mission)

@app.get("/approve")
async def approve(thread_id):
    await executeGraph("approve", thread_id)
    return HTMLResponse("""
        <h2>✅ Candidature approuvée</h2>
        <p>Vous pouvez fermer cette page.</p>
    """)


@app.get("/reject")
async def reject(thread_id):
    await executeGraph("reject", thread_id)
    return HTMLResponse("""
        <h2>✅ Candidature rejettée</h2>
        <p>Vous pouvez fermer cette page.</p>
    """)


@app.post("/modify")
async def modify(thread_id: str = Form(...), candidate: str = Form(...)):
    async with AsyncPostgresSaver.from_conn_string(os.environ["SUPABASE_DATABASE_URL"]) as checkpointerPostGre:
        await checkpointerPostGre.setup()
        graph_mission = start(checkpointerPostGre)
        config_mission = {"configurable": {"thread_id": thread_id}}
        await graph_mission.ainvoke(Command(resume={ "action":"modify", "updated_candidate": candidate}),config=config_mission)
    return HTMLResponse("""
        <h2>✅ Candidature modifiée</h2>
        <p>Vous pouvez fermer cette page.</p>
    """)


@app.get("/modify")
async def call_modify(request: Request, thread_id):
    async with AsyncPostgresSaver.from_conn_string(os.environ["SUPABASE_DATABASE_URL"]) as checkpointerPostGre:
        await checkpointerPostGre.setup()
        graph_mission = start(checkpointerPostGre)
        config_mission = {"configurable": {"thread_id": thread_id}}
        subgraph_state = await graph_mission.aget_state(config_mission)
        new_state = subgraph_state.values
        candidate = new_state["candidate"]
        name = new_state["mission"]["name"]
        context = {
            "thread_id": thread_id,
            "candidate": candidate,
            "name": name
        }
        return templates.TemplateResponse(
            request=request, name="modify.html", context=context
        )