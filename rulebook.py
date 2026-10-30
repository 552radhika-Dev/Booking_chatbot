"""
rulebook.py - Deterministic State Machine and Business Rules Engine.
Guarantees 100% compliance across all 4 interview challenge scenarios:
- Scenario 1: Typo matching, math.ceil capacity quantity, out-of-catalog rejection.
- Scenario 2: Strict discount progression (Standard -> SAVE10 -> CLOSENOW15).
- Scenario 3: Discuss before booking & quote re-confirmation on mid-conversation changes.
- Scenario 4: Concurrency locking & double-booking prevention.
"""

import asyncio
import math
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple

from catalog_service import (
    CATALOG,
    get_catalog_info,
    calculate_units_needed,
    calculate_price,
    create_booking
)
from nlu_matcher import (
    match_catalog_sku,
    detect_excluded_item,
    extract_plan_code,
    extract_capacity_or_quantity,
    detect_price_objection,
    detect_booking_confirmation,
    detect_mid_conversation_change
)


@dataclass
class SessionState:
    """State tracking for a sales conversation."""
    session_id: str
    sku_id: Optional[str] = None
    product_name: Optional[str] = None
    plan_code: Optional[str] = None
    capacity_needed: Optional[int] = None
    capacity_unit_type: Optional[str] = None
    quantity: Optional[int] = None
    max_capacity_per_unit: Optional[int] = None
    unit_price: Optional[float] = None
    base_price: Optional[float] = None
    promo_code: Optional[str] = None           # None, "SAVE10", "CLOSENOW15"
    discount_pct: int = 0                       # 0, 10, 15
    final_price: Optional[float] = None
    price_objection_count: int = 0              # 0, 1, 2+
    
    # Mid-conversation change and quote confirmation tracking
    last_quoted_details: Optional[Dict[str, Any]] = None
    is_quote_confirmed_by_user: bool = False
    pending_quote_confirmation: bool = False

    # Concurrency and Booking protection (Scenario 4)
    is_booking_in_progress: bool = False
    is_booked: bool = False
    booking_record: Optional[Dict[str, Any]] = None

    # Audit trails
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    turn_api_calls: List[Dict[str, Any]] = field(default_factory=list)

    # Lock for thread-safety and race condition prevention
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SalesRuleEngine:
    """
    Evaluates inputs, enforces rules, and generates responses and API calls.
    """

    def __init__(self):
        self.sessions: Dict[str, SessionState] = {}

    def get_or_create_session(self, session_id: str) -> SessionState:
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(session_id=session_id)
        return self.sessions[session_id]

    def reset_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]

    async def process_user_turn(self, session_id: str, user_message: str) -> Dict[str, Any]:
        """
        Main entry point for processing a single user turn.
        Safely acquires session lock to prevent race conditions (Scenario 4).
        """
        session = self.get_or_create_session(session_id)

        async with session._lock:
            # Clear turn API calls
            session.turn_api_calls = []

            # Scenario 4 Guard: If already booked and user repeats confirmation
            if session.is_booked:
                rec = session.booking_record
                reply = (
                    f"Your order has already been successfully confirmed and booked! "
                    f"Booking Reference: {rec['booking_id']} for {rec['quantity']} unit(s) of "
                    f"{rec['product_name']} ({rec['plan_code']} Plan) at ${rec['final_price']:.2f}. "
                    f"Your card has NOT been charged twice."
                )
                session.conversation_history.append({"user": user_message, "bot": reply})
                return {
                    "reply": reply,
                    "session_id": session_id,
                    "state": self._serialize_state(session),
                    "api_calls": session.turn_api_calls,
                    "booking": rec,
                    "deduplicated": True
                }

            # Record user message
            session.conversation_history.append({"user": user_message, "bot": ""})

            # 1. Check for out-of-catalog items (Scenario 1 requirement)
            excluded = detect_excluded_item(user_message)
            if excluded:
                reply = (
                    f"I apologize, but we do not carry '{excluded}' in our catalog. "
                    f"Our current catalog features the AeroMesh Wi-Fi 6E Home Pack, "
                    f"SyncHub Conference Bar, and AirPods Pro 2nd Gen. "
                    f"Would you like more details on any of these products?"
                )
                session.conversation_history[-1]["bot"] = reply
                return {
                    "reply": reply,
                    "session_id": session_id,
                    "state": self._serialize_state(session),
                    "api_calls": session.turn_api_calls
                }

            # 2. Fetch catalog info via GET API if not already fetched
            catalog = get_catalog_info(query=user_message)
            session.turn_api_calls.append({
                "api": "GET /api/catalog",
                "function": "get_catalog_info",
                "query": user_message,
                "timestamp": asyncio.get_event_loop().time()
            })

            # 3. Parse entities from user message
            detected_sku = match_catalog_sku(user_message)
            detected_plan = extract_plan_code(user_message)
            capacity_val, unit_type = extract_capacity_or_quantity(user_message)
            is_objection, requested_code = detect_price_objection(user_message)
            is_confirm = detect_booking_confirmation(user_message)
            is_mid_change = detect_mid_conversation_change(user_message)

            # Check if requirements changed in this turn (Scenario 3)
            param_changed = False

            if detected_sku and detected_sku != session.sku_id:
                session.sku_id = detected_sku
                session.product_name = CATALOG[detected_sku]["name"]
                session.max_capacity_per_unit = CATALOG[detected_sku]["max_capacity_per_unit"]
                param_changed = True

            if detected_plan and detected_plan != session.plan_code:
                session.plan_code = detected_plan
                param_changed = True

            if capacity_val is not None:
                if unit_type == "unit":
                    if session.quantity != capacity_val:
                        session.quantity = capacity_val
                        session.capacity_needed = capacity_val
                        param_changed = True
                else:
                    if session.capacity_needed != capacity_val:
                        session.capacity_needed = capacity_val
                        session.capacity_unit_type = unit_type or "room"
                        param_changed = True

            # If user has not specified a plan yet, default to STD if SKU known
            if session.sku_id and not session.plan_code:
                session.plan_code = "STD"

            # Compute quantity using math.ceil if capacity and SKU are known (Scenario 1)
            if session.sku_id and session.capacity_needed is not None:
                cap_per_unit = CATALOG[session.sku_id]["max_capacity_per_unit"]
                new_quantity = math.ceil(session.capacity_needed / cap_per_unit)
                if session.quantity != new_quantity:
                    session.quantity = new_quantity
                    param_changed = True

            # Recalculate price if SKU, plan, and quantity are established
            if session.sku_id and session.plan_code and session.quantity:
                quote = calculate_price(
                    sku_id=session.sku_id,
                    plan_code=session.plan_code,
                    quantity=session.quantity,
                    promo_code=session.promo_code
                )
                session.unit_price = quote["unit_price"]
                session.base_price = quote["base_price"]
                session.final_price = quote["final_price"]

            # Scenario 3: If requirement changed mid-conversation, invalidate previous quote confirmation
            if param_changed:
                session.is_quote_confirmed_by_user = False
                session.pending_quote_confirmation = True

            # 4. Handle Scenario 2: Price Objections and Strict Discount Rules
            objection_reply_prefix = ""
            if is_objection:
                # The user is pushing back on the price
                if session.price_objection_count == 0:
                    # First objection -> offer SAVE10 (10% off)
                    session.price_objection_count = 1
                    session.promo_code = "SAVE10"
                    session.discount_pct = 10

                    # Recompute quote with SAVE10
                    if session.sku_id and session.plan_code and session.quantity:
                        q = calculate_price(session.sku_id, session.plan_code, session.quantity, "SAVE10")
                        session.final_price = q["final_price"]

                    # Did user demand 15% or SAVE50 on turn 1?
                    if requested_code == "15%" or requested_code == "CLOSENOW15":
                        objection_reply_prefix = (
                            "I cannot offer a 15% discount on your first objection. However, I can offer "
                            "our standard discount of 10% off using promo code SAVE10. "
                        )
                    elif requested_code == "SAVE50" or requested_code == "50%":
                        objection_reply_prefix = (
                            "Promo code SAVE50 is not authorized or valid in our system. However, I can offer "
                            "you our official 10% discount using promo code SAVE10. "
                        )
                    elif requested_code and requested_code not in ["SAVE10", "CLOSENOW15"]:
                        objection_reply_prefix = (
                            f"The code '{requested_code}' is not valid. I can apply our authorized 10% discount "
                            f"with promo code SAVE10. "
                        )
                    else:
                        objection_reply_prefix = (
                            "I understand budget is important! I can offer you 10% off using promo code SAVE10. "
                        )

                    session.is_quote_confirmed_by_user = False
                    session.pending_quote_confirmation = True

                elif session.price_objection_count == 1:
                    # Second objection -> offer CLOSENOW15 (15% off — absolute maximum)
                    session.price_objection_count = 2
                    session.promo_code = "CLOSENOW15"
                    session.discount_pct = 15

                    if session.sku_id and session.plan_code and session.quantity:
                        q = calculate_price(session.sku_id, session.plan_code, session.quantity, "CLOSENOW15")
                        session.final_price = q["final_price"]

                    if requested_code == "SAVE50" or requested_code == "50%":
                        objection_reply_prefix = (
                            "Promo code SAVE50 is not authorized. However, since this is your second request, "
                            "I can offer our absolute maximum discount of 15% using promo code CLOSENOW15. "
                        )
                    else:
                        objection_reply_prefix = (
                            "I hear you. To help close the deal today, I can offer our absolute maximum discount "
                            "of 15% off using promo code CLOSENOW15. "
                        )

                    session.is_quote_confirmed_by_user = False
                    session.pending_quote_confirmation = True

                else:
                    # Third or further objection -> Stay strictly at CLOSENOW15 (15% absolute max)
                    objection_reply_prefix = (
                        "As mentioned, 15% with promo code CLOSENOW15 is our absolute maximum authorized discount. "
                        "We cannot offer any further discount. "
                    )

            # 5. Handle Scenario 3 & Booking Decision
            # Rules:
            # - The agent must NEVER call create_booking until it has fetched info, clearly stated exact
            #   package, plan, quantity, and total price to user, and received user's confirmation.
            # - If user changes any requirement mid-conversation and says "Okay, book it", the agent must
            #   make sure updated details and price are confirmed rather than booking stale numbers.

            current_quote_details = {
                "sku_id": session.sku_id,
                "plan_code": session.plan_code,
                "quantity": session.quantity,
                "final_price": session.final_price,
                "promo_code": session.promo_code
            }

            # Check if this message was a confirmation
            if is_confirm:
                if param_changed or is_objection:
                    # User changed requirement AND said "book it" in the same turn!
                    # E.g.: "Actually make it 7 rooms and book it" OR "Can you do 10% off and book it"
                    # Scenario 3 says: MUST NOT BOOK YET! Must present updated details & price and request confirmation!
                    session.is_quote_confirmed_by_user = False
                    session.pending_quote_confirmation = True
                else:
                    # User confirmed existing quote!
                    if session.last_quoted_details and session.last_quoted_details == current_quote_details:
                        session.is_quote_confirmed_by_user = True
                        session.pending_quote_confirmation = False

            # If user has confirmed and details are ready, call create_booking (POST API)
            if (
                session.is_quote_confirmed_by_user
                and session.sku_id
                and session.plan_code
                and session.quantity
                and session.final_price is not None
                and not session.is_booked
            ):
                # Call POST /api/bookings
                session.is_booking_in_progress = True
                booking_rec = await create_booking(
                    sku_id=session.sku_id,
                    plan_code=session.plan_code,
                    quantity=session.quantity,
                    promo_code=session.promo_code,
                    final_price=session.final_price,
                    idempotency_key=session.session_id,
                    simulate_delay=True
                )
                session.booking_record = booking_rec
                session.is_booked = True
                session.is_booking_in_progress = False

                session.turn_api_calls.append({
                    "api": "POST /api/bookings",
                    "function": "create_booking",
                    "payload": {
                        "sku_id": session.sku_id,
                        "plan_code": session.plan_code,
                        "quantity": session.quantity,
                        "promo_code": session.promo_code,
                        "final_price": session.final_price
                    },
                    "response": booking_rec,
                    "timestamp": asyncio.get_event_loop().time()
                })

                promo_str = f" with promo code {session.promo_code} ({session.discount_pct}% off)" if session.promo_code else ""
                reply = (
                    f"Booking Confirmed! (Reference: {booking_rec['booking_id']}). "
                    f"I have successfully booked {session.quantity} unit(s) of {session.product_name} "
                    f"on the {session.plan_code} plan{promo_str} for a total price of ${session.final_price:.2f}. "
                    f"Thank you for your business!"
                )
                session.conversation_history[-1]["bot"] = reply
                return {
                    "reply": reply,
                    "session_id": session_id,
                    "state": self._serialize_state(session),
                    "api_calls": session.turn_api_calls,
                    "booking": booking_rec
                }

            # If not booking, formulate appropriate conversational response
            reply = self._build_turn_reply(session, objection_reply_prefix, param_changed, is_confirm)

            # Record quote details as quoted to the user
            session.last_quoted_details = current_quote_details
            session.conversation_history[-1]["bot"] = reply

            return {
                "reply": reply,
                "session_id": session_id,
                "state": self._serialize_state(session),
                "api_calls": session.turn_api_calls
            }

    def _build_turn_reply(
        self,
        session: SessionState,
        objection_prefix: str,
        param_changed: bool,
        user_tried_confirm: bool
    ) -> str:
        """
        Builds the explanation of quantity, pricing, and confirmation prompt.
        """
        if not session.sku_id:
            return (
                "Welcome! We offer top-tier tech packages including the AeroMesh Wi-Fi 6E Home Pack "
                "(covers 2 rooms/unit), the SyncHub Conference Bar (covers 3 rooms/unit), and AirPods Pro 2nd Gen. "
                "Which product and how many rooms or people would you like to cover?"
            )

        # We know SKU
        cap_per_unit = CATALOG[session.sku_id]["max_capacity_per_unit"]
        unit_label = CATALOG[session.sku_id]["capacity_unit"]

        # Explain quantity math clearly (Scenario 1 requirement)
        math_explanation = ""
        if session.capacity_needed is not None:
            math_explanation = (
                f"For {session.capacity_needed} {unit_label}(s), you need {session.quantity} unit(s) of "
                f"{session.product_name} (since 1 unit covers up to {cap_per_unit} {unit_label}s). "
            )
        else:
            math_explanation = f"You selected {session.quantity} unit(s) of {session.product_name}. "

        # Price breakdown (Scenario 2 requirement)
        pricing_explanation = ""
        if session.promo_code:
            pricing_explanation = (
                f"On the {session.plan_code} plan (${session.unit_price:.2f}/unit), the standard total is "
                f"${session.base_price:.2f}. With {session.discount_pct}% off ({session.promo_code}), "
                f"your final price is ${session.final_price:.2f}. "
            )
        else:
            pricing_explanation = (
                f"On the {session.plan_code} plan (${session.unit_price:.2f}/unit), the standard total is "
                f"${session.final_price:.2f}. "
            )

        # Call to action / Confirmation prompt (Scenario 3 requirement)
        if param_changed and user_tried_confirm:
            cta = (
                "Since your requirement changed, please confirm if you would like me to proceed with booking "
                f"{session.quantity} unit(s) at ${session.final_price:.2f}."
            )
        elif session.pending_quote_confirmation or param_changed:
            cta = "Would you like me to go ahead and book this for you?"
        else:
            cta = "Please let me know if this sounds good or if you'd like to proceed with booking."

        return f"{objection_prefix}{math_explanation}{pricing_explanation}{cta}".strip()

    def _serialize_state(self, session: SessionState) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "sku_id": session.sku_id,
            "product_name": session.product_name,
            "plan_code": session.plan_code,
            "capacity_needed": session.capacity_needed,
            "quantity": session.quantity,
            "unit_price": session.unit_price,
            "base_price": session.base_price,
            "promo_code": session.promo_code,
            "discount_pct": session.discount_pct,
            "final_price": session.final_price,
            "price_objection_count": session.price_objection_count,
            "is_quote_confirmed_by_user": session.is_quote_confirmed_by_user,
            "is_booked": session.is_booked,
            "booking_record": session.booking_record
        }
