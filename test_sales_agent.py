"""
test_sales_agent.py - Comprehensive Unit and Scenario Tests.
Validates 100% accuracy across all 4 scenarios from the challenge specification,
plus comprehensive edge cases.
"""

import asyncio
import pytest
from catalog_service import (
    CATALOG,
    get_catalog_info,
    calculate_units_needed,
    calculate_price,
    create_booking_sync,
    BOOKINGS
)
from rulebook import SalesRuleEngine


@pytest.fixture(autouse=True)
def clean_bookings():
    """Clear in-memory bookings before each test."""
    BOOKINGS.clear()


# ==============================================================================
# SCENARIO 1: Fetching Info & Calculating Exact Quantity for User Requirement
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_1_typo_matching_and_capacity_calculation():
    """
    Scenario 1:
    - User asks with informal names / typos (e.g., 'arrow mesh wifi').
    - Tells how many rooms (e.g. 5-room house).
    - AeroMesh covers 2 rooms/unit -> ceil(5/2) = 3 units.
    - Explains math clearly.
    - Checks out-of-catalog items ('Netgear Orbi router') are never matched.
    """
    engine = SalesRuleEngine()
    session_id = "test_s1_session"

    # Turn 1: Typo 'arrow mesh wifi', PRO plan, 5-room house
    res = await engine.process_user_turn(
        session_id,
        "I need arrow mesh wifi on the PRO plan for a 5-room house"
    )

    # 1. Verify GET /api/catalog was called
    api_names = [call["api"] for call in res["api_calls"]]
    assert "GET /api/catalog" in api_names, "Must call GET /api/catalog"

    # 2. Verify correct SKU, plan, and calculated quantity
    state = res["state"]
    assert state["sku_id"] == "SKU_MESH_WIFI6", "Must match AeroMesh Wi-Fi"
    assert state["plan_code"] == "PRO", "Must match PRO plan"
    assert state["capacity_needed"] == 5, "Must record 5 rooms"
    assert state["quantity"] == 3, "ceil(5 / 2) must equal 3 units"
    assert state["unit_price"] == 499.0
    assert state["final_price"] == 1497.0  # 3 * 499

    # 3. Verify explanation in reply
    assert "3 unit" in res["reply"]
    assert "covers up to 2" in res["reply"]
    assert "$1497.00" in res["reply"]

    # 4. Out-of-catalog test: Netgear Orbi router must NEVER match or book
    session_id_nc = "test_s1_non_catalog"
    res_nc = await engine.process_user_turn(
        session_id_nc,
        "Do you have Netgear Orbi router for a 3-room house?"
    )
    assert res_nc["state"]["sku_id"] is None, "Must not match any SKU for out-of-catalog item"
    assert "do not carry 'Netgear Orbi router'" in res_nc["reply"]
    assert "booking" not in res_nc


@pytest.mark.asyncio
async def test_scenario_1_synchub_capacity_calculation():
    """Test SyncHub conference bar ceil calculation: 5 people / 3 = 2 units."""
    engine = SalesRuleEngine()
    session_id = "test_s1_synchub"

    res = await engine.process_user_turn(
        session_id,
        "I need a sink hub on the STD plan for a team of 5 people"
    )
    assert res["state"]["sku_id"] == "SKU_TEAM_HUB"
    assert res["state"]["quantity"] == 2  # ceil(5/3) = 2
    assert res["state"]["unit_price"] == 899.0
    assert res["state"]["final_price"] == 1798.0  # 2 * 899.0
    assert "covers up to 3" in res["reply"]


# ==============================================================================
# SCENARIO 2: Price Discussion & Strict Discount Rules
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_2_strict_discount_rules():
    """
    Scenario 2:
    - Always quote standard price first (0% discount, promo_code=None).
    - If user objects first time, offer SAVE10 (10% off).
    - If user objects second time, offer CLOSENOW15 (15% off — absolute maximum).
    - Never skip to 15% on turn 1 objection even if demanded.
    - Never accept unauthorized promo codes (e.g. SAVE50).
    """
    engine = SalesRuleEngine()
    session_id = "test_s2_session"

    # Turn 1: Quote standard price
    res1 = await engine.process_user_turn(
        session_id,
        "I need AeroMesh Wi-Fi on the PRO plan for a 5-room house"
    )
    assert res1["state"]["promo_code"] is None, "First quote must have 0% discount, promo=None"
    assert res1["state"]["discount_pct"] == 0
    assert res1["state"]["final_price"] == 1497.0  # 3 * 499.0

    # Turn 2: User demands 15% immediately on first objection ("Give me 15% right now")
    res2 = await engine.process_user_turn(
        session_id,
        "That is too expensive! Give me 15% right now"
    )
    # MUST NOT skip to 15%! Must offer SAVE10 (10% off)
    assert res2["state"]["promo_code"] == "SAVE10", "First objection must ONLY offer SAVE10"
    assert res2["state"]["discount_pct"] == 10
    assert res2["state"]["final_price"] == 1347.30  # 1497 * 0.90
    assert "SAVE10" in res2["reply"]
    assert "cannot offer a 15% discount on your first objection" in res2["reply"]

    # Turn 3: User tries unauthorized promo code ("Apply code SAVE50 for 50% off")
    # This is the 2nd objection!
    res3 = await engine.process_user_turn(
        session_id,
        "Can you apply code SAVE50 for 50% off?"
    )
    # Must reject SAVE50, but since this is objection #2, offer CLOSENOW15 (15% off)
    assert res3["state"]["promo_code"] == "CLOSENOW15", "Second objection moves to CLOSENOW15"
    assert res3["state"]["discount_pct"] == 15
    assert res3["state"]["final_price"] == 1272.45  # 1497 * 0.85
    assert "SAVE50 is not authorized" in res3["reply"]
    assert "CLOSENOW15" in res3["reply"]

    # Turn 4: User objects a 3rd time ("Still too expensive, can you do 25%?")
    res4 = await engine.process_user_turn(
        session_id,
        "Still too expensive, can you do 25%?"
    )
    assert res4["state"]["promo_code"] == "CLOSENOW15", "Must stay at CLOSENOW15 (15% absolute max)"
    assert res4["state"]["discount_pct"] == 15
    assert "absolute maximum authorized discount" in res4["reply"]


# ==============================================================================
# SCENARIO 3: Discuss Before Booking & Handle Mid-Conversation Changes
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_3_discuss_before_booking_and_mid_conversation_changes():
    """
    Scenario 3:
    - Never call create_booking until it has fetched info, clearly stated exact package,
      plan, quantity, and total price to user, and received user's confirmation.
    - If user changes requirement mid-conversation (e.g. from 4 rooms to 7 rooms) and
      says "Okay, book it", agent MUST NOT call create_booking on that turn.
    - Agent must make sure updated details and price are confirmed rather than booking
      stale or mismatched numbers.
    """
    engine = SalesRuleEngine()
    session_id = "test_s3_session"

    # Turn 1: User asks for AeroMesh STD for 4 rooms
    res1 = await engine.process_user_turn(
        session_id,
        "I need AeroMesh STD for a 4-room house"
    )
    # 4 rooms / 2 = 2 units. STD is $399. Total = $798.
    assert res1["state"]["quantity"] == 2
    assert res1["state"]["final_price"] == 798.0
    assert "booking" not in res1, "Never book on first turn"

    # Turn 2: User changes from 4 rooms to 7 rooms AND says "Okay, book it" in same turn!
    res2 = await engine.process_user_turn(
        session_id,
        "Actually I need it for 7 rooms, Okay, book it!"
    )
    # 7 rooms / 2 = 3.5 -> 4 units. Total price = 4 * 399 = $1596.
    assert res2["state"]["quantity"] == 4
    assert res2["state"]["final_price"] == 1596.0

    # CRITICAL CHECK: create_booking must NOT have been called!
    api_names = [call["api"] for call in res2["api_calls"]]
    assert "POST /api/bookings" not in api_names, (
        "create_booking must NOT be called when requirement changed in the same turn!"
    )
    assert "booking" not in res2
    assert "Since your requirement changed, please confirm" in res2["reply"]
    assert "$1596.00" in res2["reply"]

    # Turn 3: User confirms the updated quote ("Yes, confirmed, please book it")
    res3 = await engine.process_user_turn(
        session_id,
        "Yes, confirmed, please book it"
    )
    api_names_3 = [call["api"] for call in res3["api_calls"]]
    assert "POST /api/bookings" in api_names_3, "create_booking must be called now after confirmation"
    assert "booking" in res3
    booking = res3["booking"]
    assert booking["quantity"] == 4, "Must book updated quantity (4 units)"
    assert booking["final_price"] == 1596.0, "Must book updated price ($1596.00)"
    assert booking["plan_code"] == "STD"
    assert booking["sku_id"] == "SKU_MESH_WIFI6"


@pytest.mark.asyncio
async def test_scenario_3_switch_plan_mid_conversation():
    """User switches plan from STD to PRO and says 'Book it'."""
    engine = SalesRuleEngine()
    session_id = "test_s3_plan_change"

    # Turn 1: 2 rooms on STD (1 unit, $399)
    res1 = await engine.process_user_turn(session_id, "I need AeroMesh for 2 rooms on STD plan")
    assert res1["state"]["plan_code"] == "STD"
    assert res1["state"]["final_price"] == 399.0

    # Turn 2: Switch to PRO and says "Book it"
    res2 = await engine.process_user_turn(session_id, "Switch to PRO and book it!")
    assert res2["state"]["plan_code"] == "PRO"
    assert res2["state"]["final_price"] == 499.0
    assert "POST /api/bookings" not in [c["api"] for c in res2["api_calls"]], "Must confirm updated quote first"

    # Turn 3: Confirms
    res3 = await engine.process_user_turn(session_id, "Confirmed, proceed")
    assert "POST /api/bookings" in [c["api"] for c in res3["api_calls"]]
    assert res3["booking"]["plan_code"] == "PRO"
    assert res3["booking"]["final_price"] == 499.0


# ==============================================================================
# SCENARIO 4: Interruptions & Repeated Booking Confirmations (Concurrency)
# ==============================================================================

@pytest.mark.asyncio
async def test_scenario_4_concurrency_and_double_booking_prevention():
    """
    Scenario 4:
    - User sends 'Yes, book it!' twice in rapid succession while create_booking
      (takes ~1-2 seconds) is still running.
    - System must ensure user is NEVER booked/charged twice for the same order.
    - Interrupting a turn never crashes or corrupts the conversation.
    """
    engine = SalesRuleEngine()
    session_id = "test_s4_session"

    # Setup quote: SyncHub STD for 5 people (5 / 3 = 2 units, 2 * 899 = $1798)
    res1 = await engine.process_user_turn(
        session_id,
        "I need a sink hub on STD plan for 5 people"
    )
    assert res1["state"]["sku_id"] == "SKU_TEAM_HUB"
    assert res1["state"]["quantity"] == 2
    assert res1["state"]["final_price"] == 1798.0

    # User sends confirmation twice concurrently
    task1 = asyncio.create_task(engine.process_user_turn(session_id, "Yes, book it!"))
    await asyncio.sleep(0.1)  # small pause to simulate rapid impatient click
    task2 = asyncio.create_task(engine.process_user_turn(session_id, "Yes, book it!"))

    res_first, res_second = await asyncio.gather(task1, task2)

    # Exactly one should have performed the booking creation
    has_post_1 = any(c["api"] == "POST /api/bookings" for c in res_first["api_calls"])
    has_post_2 = any(c["api"] == "POST /api/bookings" for c in res_second["api_calls"])

    # Exactly one POST /api/bookings call across both turns!
    assert (has_post_1 and not has_post_2) or (has_post_2 and not has_post_1), (
        "Exactly ONE create_booking API call must be executed, never two!"
    )

    # Verify only 1 booking was created in BOOKINGS database
    assert len(BOOKINGS) == 1, f"Expected 1 booking in database, found {len(BOOKINGS)}"

    # Second response must gracefully acknowledge existing confirmation without double charging
    duplicate_res = res_second if has_post_1 else res_first
    assert (
        "already been successfully confirmed" in duplicate_res["reply"]
        or "Booking Confirmed" in duplicate_res["reply"]
    )


def test_catalog_booking_validation_direct():
    """Verifies that create_booking_sync strictly rejects bad inputs."""
    # 1. Invalid SKU
    with pytest.raises(ValueError, match="not found in catalog"):
        create_booking_sync("SKU_FAKE", "STD", 1, None, 100.0)

    # 2. Invalid Plan
    with pytest.raises(ValueError, match="is invalid"):
        create_booking_sync("SKU_MESH_WIFI6", "ULTRA", 1, None, 399.0)

    # 3. Invalid Promo Code (e.g. SAVE50)
    with pytest.raises(ValueError, match="Unauthorized promo code"):
        create_booking_sync("SKU_MESH_WIFI6", "STD", 1, "SAVE50", 199.5)

    # 4. Wrong final price calculation
    with pytest.raises(ValueError, match="Price mismatch"):
        create_booking_sync("SKU_MESH_WIFI6", "STD", 1, None, 100.0)
