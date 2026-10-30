"""
nlu_matcher.py - Intent, entity, and typo extraction engine.
Handles informal names, typos, capacity calculation inputs, price objections,
and mid-conversation changes.
"""

import re
from typing import Dict, Any, Optional, List, Tuple
from catalog_service import CATALOG, EXCLUDED_CATALOG_ITEMS


def normalize_text(text: str) -> str:
    """Lowercases, preserves alphanumeric, %, hyphens, and standardizes spaces."""
    text = text.lower()
    text = re.sub(r"[^\w\s%-]", " ", text)
    return " ".join(text.split())


def detect_excluded_item(text: str) -> Optional[str]:
    """
    Checks if user is asking for an item not in our catalog.
    e.g. 'Netgear Orbi router', 'Eero', 'Google Nest'
    Scenario 1 requirement: It must NEVER match or book our item by mistake!
    """
    normalized = normalize_text(text)
    for exc in EXCLUDED_CATALOG_ITEMS:
        pattern = r"\b" + re.escape(exc) + r"\b"
        if re.search(pattern, normalized):
            if "orbi" in normalized or "netgear" in normalized:
                return "Netgear Orbi router"
            return exc.title()
    return None


def match_catalog_sku(text: str) -> Optional[str]:
    """
    Matches user query to SKU using alias matching and typo tolerance.
    Handles 'arrow mesh wifi', 'sink hub', 'air pods pro', etc.
    """
    # First ensure it's not an excluded out-of-catalog item
    if detect_excluded_item(text):
        return None

    normalized = normalize_text(text)

    # Priority 1: Exact alias substring match
    for sku, data in CATALOG.items():
        for alias in data["aliases"]:
            if alias in normalized:
                return sku

    # Priority 2: Keyword tokens
    if any(k in normalized for k in ["arrow mesh", "aeromesh", "mesh wifi", "arrow wifi", "aero mesh"]):
        return "SKU_MESH_WIFI6"
    if any(k in normalized for k in ["sink hub", "synchub", "sync hub", "conference bar", "sinkhub"]):
        return "SKU_TEAM_HUB"
    if any(k in normalized for k in ["airpod", "airpods", "air pods", "earbud", "earbuds"]):
        return "SKU_AIRPODS_PRO2"

    return None


def extract_plan_code(text: str) -> Optional[str]:
    """
    Extracts plan code from user message ('PRO', 'STD', 'CARE').
    """
    normalized = normalize_text(text)

    if re.search(r"\b(pro|professional)\b", normalized):
        return "PRO"
    if re.search(r"\b(care|applecare|protection)\b", normalized):
        return "CARE"
    if re.search(r"\b(std|standard|basic)\b", normalized):
        return "STD"

    return None


def extract_capacity_or_quantity(text: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Extracts number of rooms, people, or direct units.
    Safely ignores discount percentages like '50% off' or 'for 50%'.
    Returns: (number, unit_type) e.g. (5, 'room'), (3, 'people'), (2, 'unit')
    """
    normalized = normalize_text(text)

    # Clean out percentages and promo code tokens so they never get misparsed as rooms
    cleaned = re.sub(r"\b\d+\s*(?:%|percent)\b(?:\s*off|\s*discount)?", " ", normalized)
    cleaned = re.sub(r"\bsave\d+\b", " ", cleaned)
    cleaned = re.sub(r"\bclosenow\d+\b", " ", cleaned)
    cleaned = " ".join(cleaned.split())

    # Look for room patterns: e.g. "5 room", "5-room", "5 rooms", "5 bedroom", "house with 5 rooms"
    room_match = re.search(r"(\d+)\s*(?:-| )*(?:room|rooms|bedroom|bedrooms|house)\b", cleaned)
    if room_match:
        return int(room_match.group(1)), "room"

    # Look for people patterns: e.g. "5 people", "3 persons", "4 users", "6 members"
    people_match = re.search(r"(\d+)\s*(?:-| )*(?:people|person|persons|users|user|attendees|members)\b", cleaned)
    if people_match:
        return int(people_match.group(1)), "people"

    # Look for direct unit / pack patterns: e.g. "3 units", "2 packs", "1 piece"
    unit_match = re.search(r"(\d+)\s*(?:-| )*(?:units|unit|pack|packs|devices|items|piece|pieces)\b", cleaned)
    if unit_match:
        return int(unit_match.group(1)), "unit"

    # Fallback: standalone number if accompanied by context like "for 5" or "need 5" or "make it 7"
    context_match = re.search(r"(?:for|need|have|got|make it|change to|from \d+ to)\s+(\d+)\b", cleaned)
    if context_match:
        val = int(context_match.group(1))
        # Extra guard: room counts are reasonable (1-20), discount percentages were stripped
        if 1 <= val <= 30:
            return val, "count"

    return None, None


def detect_price_objection(text: str) -> Tuple[bool, Optional[str]]:
    """
    Detects if user is objecting to the price, asking for a discount,
    pushing back, or demanding a specific code / percentage.
    Returns: (is_objection, requested_code_or_pct)
    """
    normalized = normalize_text(text)

    # Check for specific promo codes demanded by user
    if "save50" in normalized:
        return True, "SAVE50"
    if "save10" in normalized:
        return True, "SAVE10"
    if "closenow15" in normalized:
        return True, "CLOSENOW15"
    if "50%" in normalized or "50 percent" in normalized or "50 %" in normalized:
        return True, "50%"
    if "15%" in normalized or "15 percent" in normalized or "15 %" in normalized or "give me 15" in normalized:
        return True, "15%"
    if "10%" in normalized or "10 percent" in normalized or "10 %" in normalized:
        return True, "10%"

    # General price pushback indicators
    objection_keywords = [
        "too expensive", "expensive", "price is high", "too high", "costly",
        "lower the price", "lower price", "discount", "any discount",
        "better price", "cheaper", "reduce price", "best price",
        "push back", "negotiate", "cant afford", "can't afford",
        "more than my budget", "out of budget", "give me a deal",
        "any offer", "coupon", "promo code", "give me a discount",
        "do better on price", "special price", "best offer", "can you do better"
    ]

    for kw in objection_keywords:
        if kw in normalized:
            return True, None

    return False, None


def detect_booking_confirmation(text: str) -> bool:
    """
    Detects if user confirms/approves booking.
    e.g., 'Yes, book it', 'Okay, book it', 'Confirm booking', 'Sounds good, proceed'
    """
    normalized = normalize_text(text)

    confirm_patterns = [
        r"\b(book it|book now|confirm|confirmed|proceed|go ahead|place order|buy now)\b",
        r"\b(yes\b.*(?:book|confirm|proceed|take it|buy))",
        r"\b(sounds good|sounds great|looks good|deal|that works|perfect)\b",
        r"\b(okay book it|ok book it|yes please|yes that sounds good)\b",
        r"^(yes|yeah|yep|sure|ok|okay)\b"
    ]

    for pat in confirm_patterns:
        if re.search(pat, normalized):
            return True

    return False


def detect_mid_conversation_change(text: str) -> bool:
    """
    Detects if user is updating/changing a requirement mid-conversation.
    e.g. 'Actually make it 7 rooms', 'Change from 4 rooms to 7 rooms',
         'Switch to PRO', 'Instead of STD, give me PRO'
    """
    normalized = normalize_text(text)

    change_indicators = [
        "actually", "instead", "change to", "switch to", "make it",
        "change from", "upgrade to", "downgrade to", "updated", "rather than",
        "not 4", "make that", "how about", "what if"
    ]

    for ind in change_indicators:
        if ind in normalized:
            return True

    return False
