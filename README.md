# Agent Missions 🎯

An autonomous AI agent that hunts freelance missions — scrapes job boards, filters with Claude, generates personalized cover letters, and pauses for human validation before sending.

> Built as part of a larger multi-agent system: **Agent Bras Droit** — a personal AI assistant for freelance operations.

---

## What it does

```
1. Scrapes job boards via Apify
2. Deduplicates against Supabase (no reprocessing)
3. Filters missions with Claude based on candidate profile
4. Generates a personalized cover letter per mission
5. Sends email with approve / reject / modify links
6. Waits for human decision (interrupt)
7. Routes to reporter or discards based on decision
```

---

## Architecture

```
AgentMissionsGraph (main)
├── Scraper        → Apify Actor → List[Mission]
├── Deduplicator   → Supabase dedup + retry logic
├── Filter         → Claude (batch LLM filtering)
└── Orchestrator   → spawns one MissionGraph per eligible mission

MissionGraph (per mission)
├── Generator      → Claude cover letter
├── SendEmail      → Resend + approve/reject/modify links
├── WaitForDecision → interrupt() ← human in the loop
├── Router         → Command(resume=decision)
├── Validate       → handles modify + counter limit
└── Reporter       → sends final approved application
```

---

## Human-in-the-loop

Each mission pauses via LangGraph `interrupt()` and waits for a decision through email links:

```
✅ Approve  → /approve?thread_id=...   → sends final email
❌ Reject   → /reject?thread_id=...    → discards
✏️  Modify   → /modify?thread_id=...   → edit form → revalidate
```

Each mission runs in its own `thread_id` (mission URL) for independent state management.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | LangGraph (async) |
| LLM | Claude Haiku 4.5 (Anthropic) |
| Scraping | Apify |
| Persistence | PostgresSaver (Supabase) |
| Database | Supabase (deduplication + status tracking) |
| Email | Resend |
| API | FastAPI (webhook endpoints) |
| Monitoring | LangSmith |
| Retry | Tenacity |

---

## Key patterns

```python
# Human-in-the-loop with interrupt()
decision = interrupt({
    "question": "Que souhaitez-vous faire ?",
    "mission": mission_name,
    "candidate": candidate
})

# Resume via FastAPI endpoint
await graph.ainvoke(
    Command(resume={"action": "approve"}),
    config={"configurable": {"thread_id": thread_id}}
)

# Cross-session persistence
async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
    await checkpointer.setup()
    graph = build_graph(checkpointer)
```

---

## Project structure

```
agent-missions/
├── agent-missions.py   # Main graph (Scraper → Filter → Orchestrator)
├── mission_graph.py    # Per-mission graph (Generator → Reporter)
├── api.py              # FastAPI endpoints (approve/reject/modify)
├── prompts.py          # LLM prompts (filter + generator)
├── dictionary.py       # TypedDict state definitions
├── tools.py            # Supabase helpers + Anthropic client
└── profile.json        # Candidate profile (gitignored)
```

---

## Part of Agent Bras Droit

This agent is one module of a larger multi-agent freelance assistant:

```
Agent Bras Droit (supervisor)
├── Agent Veille      → Pain Miner (market intelligence)
├── Agent Missions    → this project
├── Agent Copy        → coming soon
├── Agent Admin       → coming soon
├── Agent Finance     → coming soon
└── Agent Support     → coming soon
```

---

## Status

**V1 — Production**  
Deployed with GitHub Actions (weekly cron) + FastAPI on Render + LangSmith monitoring.

*V2 in progress — refactoring for multi-source scraping and improved filtering.*

---

## Author

**Djamali Ali Baha Bakar** — AI Builder & Developer  
Freelance available July 2025 → contact@adsdecision.com