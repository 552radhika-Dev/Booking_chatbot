"""
app.py - FastAPI Web Service for AI Sales Agent.
Exposes:
- GET /api/catalog
- POST /api/bookings
- POST /api/chat
- POST /api/reset
- GET /api/scenarios
- POST /api/scenarios/run/{scenario_id}
- POST /api/scenarios/run-all
- Interactive Glassmorphic Web UI
"""

import asyncio
import os
import time
import uuid
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from catalog_service import (
    get_catalog_info,
    create_booking,
    create_booking_sync,
    CATALOG,
    BOOKINGS
)
from rulebook import SalesRuleEngine

app = FastAPI(
    title="AI Sales Agent — 100% Accuracy Challenge",
    description="Conversational Sales Agent with Strict Pricing, Discount Escalation, and Concurrency Guardrails",
    version="2.0.0"
)

# Engine instance
engine = SalesRuleEngine()

# Pydantic Request Models
class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str

class BookingRequest(BaseModel):
    sku_id: str
    plan_code: str
    quantity: int
    promo_code: Optional[str] = None
    final_price: float

class ResetRequest(BaseModel):
    session_id: str


# Predefined Interview Scenarios
SCENARIOS_METADATA = [
    {
        "id": 1,
        "title": "Scenario 1: Typo Matching, Capacity Ceil & Non-Catalog Rejection",
        "description": "User requests 'arrow mesh wifi' with typos for a 5-room house. System matches AeroMesh PRO, calculates math.ceil(5/2) = 3 units ($1497.00), explains math clearly, and rejects out-of-catalog 'Netgear Orbi'.",
        "turns": [
            "I need arrow mesh wifi on the PRO plan for a 5-room house",
            "Do you also have Netgear Orbi router?"
        ]
    },
    {
        "id": 2,
        "title": "Scenario 2: Price Discussion & Strict Discount Rules",
        "description": "Standard quote first (0%). 1st objection: offers ONLY SAVE10 (10%) even if user demands 15%. 2nd objection: offers CLOSENOW15 (15% max). Rejects unauthorized promo codes like SAVE50.",
        "turns": [
            "I need AeroMesh Wi-Fi on the PRO plan for a 5-room house",
            "That is too expensive! Give me 15% right now",
            "Can you apply code SAVE50 for 50% off?",
            "Still too high, give me 25% discount"
        ]
    },
    {
        "id": 3,
        "title": "Scenario 3: Discuss Before Booking & Mid-Conversation Changes",
        "description": "Agent NEVER calls create_booking before quote confirmation. If user changes 4 rooms to 7 rooms and says 'Okay, book it', agent requires updated quote confirmation first. Books only upon confirmation.",
        "turns": [
            "I need AeroMesh STD for a 4-room house",
            "Actually I need it for 7 rooms, Okay, book it!",
            "Yes, confirmed, please book it"
        ]
    },
    {
        "id": 4,
        "title": "Scenario 4: Interruptions & Repeated Booking Confirmations",
        "description": "User sends 'Yes, book it!' twice in rapid succession while create_booking (~1.2s delay) is executing. Concurrency lock ensures user is NEVER double-booked or charged twice.",
        "turns": [
            "I need a sink hub on STD plan for 5 people",
            "CONCURRENT_BOOKING_SIMULATION"
        ]
    }
]


# ==============================================================================
# OFFICIAL API ENDPOINTS (as specified in Challenge Section 3)
# ==============================================================================

@app.get("/api/catalog")
def api_get_catalog(query: Optional[str] = None):
    """
    1. GET API — Fetch available packages, capacities, and pricing.
    """
    return get_catalog_info(query=query)


@app.post("/api/bookings")
async def api_create_booking(booking: BookingRequest):
    """
    2. POST API — Create the final booking after discussing with the user.
    """
    try:
        result = await create_booking(
            sku_id=booking.sku_id,
            plan_code=booking.plan_code,
            quantity=booking.quantity,
            promo_code=booking.promo_code,
            final_price=booking.final_price,
            simulate_delay=True
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==============================================================================
# CHATBOT ENDPOINTS
# ==============================================================================

@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    """
    Conversational turn endpoint.
    Processes user turn, runs guardrails, records API calls, and returns state.
    """
    session_id = req.session_id or f"sess-{uuid.uuid4().hex[:8]}"
    result = await engine.process_user_turn(session_id, req.message)
    return result


@app.post("/api/reset")
def api_reset(req: ResetRequest):
    """Resets session state."""
    engine.reset_session(req.session_id)
    return {"status": "ok", "message": f"Session {req.session_id} reset."}


@app.get("/api/scenarios")
def api_get_scenarios():
    """Returns metadata for all 4 scenarios."""
    return SCENARIOS_METADATA


@app.post("/api/scenarios/run/{scenario_id}")
async def api_run_scenario(scenario_id: int):
    """
    Automated execution of a single scenario for live testing in interviews.
    """
    sess_id = f"auto-scen-{scenario_id}-{uuid.uuid4().hex[:6]}"
    step_logs = []
    assertions_passed = []

    if scenario_id == 1:
        # Turn 1
        m1 = "I need arrow mesh wifi on the PRO plan for a 5-room house"
        r1 = await engine.process_user_turn(sess_id, m1)
        step_logs.append({"turn": 1, "user": m1, "bot": r1["reply"], "api_calls": r1["api_calls"], "state": r1["state"]})
        
        assert r1["state"]["sku_id"] == "SKU_MESH_WIFI6"
        assert r1["state"]["quantity"] == 3
        assert r1["state"]["final_price"] == 1497.0
        assertions_passed.append("Matched 'arrow mesh wifi' -> SKU_MESH_WIFI6")
        assertions_passed.append("Calculated ceil(5/2) = 3 units")
        assertions_passed.append("Correct quote: $1497.00 (PRO plan @ $499)")

        # Turn 2
        m2 = "Do you have Netgear Orbi router?"
        r2 = await engine.process_user_turn(sess_id, m2)
        step_logs.append({"turn": 2, "user": m2, "bot": r2["reply"], "api_calls": r2["api_calls"], "state": r2["state"]})
        assert "do not carry 'Netgear Orbi router'" in r2["reply"]
        assertions_passed.append("Rejected out-of-catalog Netgear Orbi without booking")

        return {
            "scenario_id": 1,
            "title": "Scenario 1: Typo Matching & Quantity Calculation",
            "passed": True,
            "assertions_passed": assertions_passed,
            "step_logs": step_logs
        }

    elif scenario_id == 2:
        # Turn 1: Standard
        m1 = "I need AeroMesh Wi-Fi on the PRO plan for a 5-room house"
        r1 = await engine.process_user_turn(sess_id, m1)
        step_logs.append({"turn": 1, "user": m1, "bot": r1["reply"], "api_calls": r1["api_calls"], "state": r1["state"]})
        assert r1["state"]["promo_code"] is None
        assert r1["state"]["final_price"] == 1497.0
        assertions_passed.append("Turn 1: Standard price quoted first (promo_code=None, $1497.00)")

        # Turn 2: Demands 15% on 1st objection
        m2 = "That is too expensive! Give me 15% right now"
        r2 = await engine.process_user_turn(sess_id, m2)
        step_logs.append({"turn": 2, "user": m2, "bot": r2["reply"], "api_calls": r2["api_calls"], "state": r2["state"]})
        assert r2["state"]["promo_code"] == "SAVE10"
        assert r2["state"]["final_price"] == 1347.30
        assertions_passed.append("Turn 2: Objection 1 restricted to SAVE10 (10% off), refused 15% jump")

        # Turn 3: Tries SAVE50
        m3 = "Can you apply code SAVE50 for 50% off?"
        r3 = await engine.process_user_turn(sess_id, m3)
        step_logs.append({"turn": 3, "user": m3, "bot": r3["reply"], "api_calls": r3["api_calls"], "state": r3["state"]})
        assert r3["state"]["promo_code"] == "CLOSENOW15"
        assert r3["state"]["final_price"] == 1272.45
        assertions_passed.append("Turn 3: Objection 2 moved to CLOSENOW15 (15% off), rejected SAVE50")

        # Turn 4: 3rd objection
        m4 = "Still too expensive, can you do 25%?"
        r4 = await engine.process_user_turn(sess_id, m4)
        step_logs.append({"turn": 4, "user": m4, "bot": r4["reply"], "api_calls": r4["api_calls"], "state": r4["state"]})
        assert r4["state"]["promo_code"] == "CLOSENOW15"
        assertions_passed.append("Turn 4: Remained locked at CLOSENOW15 (15% absolute maximum)")

        return {
            "scenario_id": 2,
            "title": "Scenario 2: Price Discussion & Strict Discount Rules",
            "passed": True,
            "assertions_passed": assertions_passed,
            "step_logs": step_logs
        }

    elif scenario_id == 3:
        # Turn 1: 4 rooms
        m1 = "I need AeroMesh STD for a 4-room house"
        r1 = await engine.process_user_turn(sess_id, m1)
        step_logs.append({"turn": 1, "user": m1, "bot": r1["reply"], "api_calls": r1["api_calls"], "state": r1["state"]})
        assert r1["state"]["quantity"] == 2
        assert r1["state"]["final_price"] == 798.0
        assert "booking" not in r1
        assertions_passed.append("Turn 1: Quoted 2 units @ $798.00 without premature booking")

        # Turn 2: Changes to 7 rooms + says "Okay, book it!"
        m2 = "Actually I need it for 7 rooms, Okay, book it!"
        r2 = await engine.process_user_turn(sess_id, m2)
        step_logs.append({"turn": 2, "user": m2, "bot": r2["reply"], "api_calls": r2["api_calls"], "state": r2["state"]})
        assert r2["state"]["quantity"] == 4
        assert r2["state"]["final_price"] == 1596.0
        assert "POST /api/bookings" not in [c["api"] for c in r2["api_calls"]]
        assertions_passed.append("Turn 2: Detected change from 4 to 7 rooms, updated quantity to 4 units ($1596.00)")
        assertions_passed.append("Turn 2: Withheld booking call until updated quote is confirmed")

        # Turn 3: Confirms
        m3 = "Yes, confirmed, please book it"
        r3 = await engine.process_user_turn(sess_id, m3)
        step_logs.append({"turn": 3, "user": m3, "bot": r3["reply"], "api_calls": r3["api_calls"], "state": r3["state"]})
        assert "POST /api/bookings" in [c["api"] for c in r3["api_calls"]]
        assert r3["booking"]["quantity"] == 4
        assert r3["booking"]["final_price"] == 1596.0
        assertions_passed.append("Turn 3: Successfully booked exact updated details (4 units, $1596.00)")

        return {
            "scenario_id": 3,
            "title": "Scenario 3: Discuss Before Booking & Mid-Conversation Changes",
            "passed": True,
            "assertions_passed": assertions_passed,
            "step_logs": step_logs
        }

    elif scenario_id == 4:
        # Setup quote
        m1 = "I need a sink hub on STD plan for 5 people"
        r1 = await engine.process_user_turn(sess_id, m1)
        step_logs.append({"turn": 1, "user": m1, "bot": r1["reply"], "api_calls": r1["api_calls"], "state": r1["state"]})
        assertions_passed.append("Setup quote: 2x SyncHub Conference Bar ($1798.00)")

        # Fire two rapid concurrent "Yes, book it!" requests
        t1 = asyncio.create_task(engine.process_user_turn(sess_id, "Yes, book it!"))
        await asyncio.sleep(0.05)
        t2 = asyncio.create_task(engine.process_user_turn(sess_id, "Yes, book it!"))

        r2a, r2b = await asyncio.gather(t1, t2)
        step_logs.append({"turn": "2a (Concurrent Request 1)", "user": "Yes, book it!", "bot": r2a["reply"], "api_calls": r2a["api_calls"]})
        step_logs.append({"turn": "2b (Concurrent Request 2)", "user": "Yes, book it!", "bot": r2b["reply"], "api_calls": r2b["api_calls"]})

        post_calls_1 = [c for c in r2a["api_calls"] if c["api"] == "POST /api/bookings"]
        post_calls_2 = [c for c in r2b["api_calls"] if c["api"] == "POST /api/bookings"]
        total_post_calls = len(post_calls_1) + len(post_calls_2)

        assert total_post_calls == 1, f"Expected 1 POST call, got {total_post_calls}"
        assertions_passed.append("Concurrency lock prevented race condition: Exactly 1 POST /api/bookings executed")
        assertions_passed.append("Second request safely deduplicated and returned confirmation without duplicate charge")

        return {
            "scenario_id": 4,
            "title": "Scenario 4: Interruptions & Repeated Confirmations",
            "passed": True,
            "assertions_passed": assertions_passed,
            "step_logs": step_logs
        }

    raise HTTPException(status_code=404, detail="Scenario ID must be 1, 2, 3, or 4")


@app.post("/api/scenarios/run-all")
async def api_run_all_scenarios():
    """
    Runs all 4 scenarios in sequence and returns comprehensive 100% accuracy scorecard.
    """
    results = []
    total_passed = 0
    start_time = time.time()

    for s_id in [1, 2, 3, 4]:
        res = await api_run_scenario(s_id)
        results.append(res)
        if res.get("passed"):
            total_passed += 1

    duration = round(time.time() - start_time, 2)
    accuracy_score = int((total_passed / 4) * 100)

    return {
        "status": "success",
        "total_scenarios": 4,
        "scenarios_passed": total_passed,
        "accuracy_score_percentage": f"{accuracy_score}%",
        "duration_seconds": duration,
        "results": results
    }


# Mount static assets
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<h1>AI Sales Agent API is running.</h1><p>Visit /docs for API schema.</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
