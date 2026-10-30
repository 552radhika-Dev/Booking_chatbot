"""
catalog_service.py - Catalog and Booking API implementation.
Strictly implements the APIs specified in the AI Sales Agent Challenge:
1. GET /api/catalog (or get_catalog_info)
2. POST /api/bookings (or create_booking)
"""

import asyncio
import math
import time
import uuid
from typing import Dict, Any, Optional, List

# Official Catalog Data as specified in the PDF challenge
CATALOG: Dict[str, Dict[str, Any]] = {
    "SKU_AIRPODS_PRO2": {
        "name": "AirPods Pro 2nd Gen",
        "max_capacity_per_unit": 1,
        "capacity_unit": "person",
        "plans": {
            "STD": 249.0,
            "CARE": 279.0
        },
        "aliases": [
            "airpods", "air pods", "airpod", "airpods pro", "airpods pro 2",
            "airpods pro 2nd gen", "earbuds", "apple airpods", "air pod pro"
        ]
    },
    "SKU_MESH_WIFI6": {
        "name": "AeroMesh Wi-Fi 6E Home Pack",
        "max_capacity_per_unit": 2,
        "capacity_unit": "room",
        "plans": {
            "STD": 399.0,
            "PRO": 499.0
        },
        "aliases": [
            "aeromesh", "arrow mesh", "arrow mesh wifi", "aeromesh wifi",
            "aeromesh wi-fi", "aeromesh wi-fi 6e home pack", "mesh wifi",
            "mesh wifi 6e", "wifi pack", "home pack", "aero mesh", "arrowmesh",
            "arrow wifi"
        ]
    },
    "SKU_TEAM_HUB": {
        "name": "SyncHub Conference Bar",
        "max_capacity_per_unit": 3,
        "capacity_unit": "room",
        "plans": {
            "STD": 899.0,
            "PRO": 1150.0
        },
        "aliases": [
            "synchub", "sink hub", "sinkhub", "sync hub", "conference bar",
            "synchub conference bar", "sink hub conference bar", "team hub",
            "synchub bar", "sinkhub bar"
        ]
    }
}

# Known out-of-catalog items that must NEVER match
EXCLUDED_CATALOG_ITEMS = [
    "netgear", "orbi", "netgear orbi", "netgear orbi router",
    "eero", "google nest", "nest wifi", "cisco", "linksys",
    "tp-link", "asus", "asus router", "logitech", "polycom", "jabra", "bose"
]

VALID_PROMO_CODES = {
    None: 0.0,
    "SAVE10": 0.10,
    "CLOSENOW15": 0.15
}

# In-memory booking database
BOOKINGS: Dict[str, Dict[str, Any]] = {}
GLOBAL_API_CALL_LOGS: List[Dict[str, Any]] = []


def get_catalog_info(query: Optional[str] = None) -> Dict[str, Any]:
    """
    GET API — Fetch available packages, capacities, and pricing.
    Returns:
    {
      "SKU_AIRPODS_PRO2": {"name": "AirPods Pro 2nd Gen", "max_capacity_per_unit": 1, "plans": {"STD": 249.0, "CARE": 279.0}},
      "SKU_MESH_WIFI6": {"name": "AeroMesh Wi-Fi 6E Home Pack", "max_capacity_per_unit": 2, "plans": {"STD": 399.0, "PRO": 499.0}},
      "SKU_TEAM_HUB": {"name": "SyncHub Conference Bar", "max_capacity_per_unit": 3, "plans": {"STD": 899.0, "PRO": 1150.0}}
    }
    """
    clean_catalog = {}
    for sku, data in CATALOG.items():
        clean_catalog[sku] = {
            "name": data["name"],
            "max_capacity_per_unit": data["max_capacity_per_unit"],
            "plans": dict(data["plans"])
        }

    log_entry = {
        "api": "GET /api/catalog",
        "function": "get_catalog_info",
        "query": query,
        "response": clean_catalog,
        "timestamp": time.time()
    }
    GLOBAL_API_CALL_LOGS.append(log_entry)
    return clean_catalog


def calculate_units_needed(sku_id: str, capacity_needed: int) -> int:
    """
    Calculates exact quantity needed: math.ceil(capacity_needed / max_capacity_per_unit).
    For example:
    - AeroMesh covers 2 rooms per unit: 5 rooms -> ceil(5/2) = 3 units.
    - SyncHub covers 3 rooms/people per unit: 5 rooms -> ceil(5/3) = 2 units.
    - AirPods Pro covers 1 person per unit: 4 people -> ceil(4/1) = 4 units.
    """
    if sku_id not in CATALOG:
        raise ValueError(f"Unknown SKU: {sku_id}")
    cap_per_unit = CATALOG[sku_id]["max_capacity_per_unit"]
    return math.ceil(max(1, capacity_needed) / cap_per_unit)


def calculate_price(
    sku_id: str,
    plan_code: str,
    quantity: int,
    promo_code: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculates pricing:
    base_price = unit_price * quantity
    discount_amount = round(base_price * discount_pct, 2)
    final_price = round(base_price - discount_amount, 2)
    """
    if sku_id not in CATALOG:
        raise ValueError(f"Unknown SKU: {sku_id}")
    sku_data = CATALOG[sku_id]
    if plan_code not in sku_data["plans"]:
        raise ValueError(f"Invalid plan '{plan_code}' for {sku_id}. Available: {list(sku_data['plans'].keys())}")

    unit_price = sku_data["plans"][plan_code]
    base_price = round(unit_price * quantity, 2)

    if promo_code not in VALID_PROMO_CODES:
        raise ValueError(f"Invalid promo code '{promo_code}'. Valid codes: None, 'SAVE10', 'CLOSENOW15'")

    discount_rate = VALID_PROMO_CODES[promo_code]
    discount_amount = round(base_price * discount_rate, 2)
    final_price = round(base_price - discount_amount, 2)

    return {
        "sku_id": sku_id,
        "product_name": sku_data["name"],
        "plan_code": plan_code,
        "quantity": quantity,
        "unit_price": unit_price,
        "base_price": base_price,
        "promo_code": promo_code,
        "discount_pct": int(discount_rate * 100),
        "discount_amount": discount_amount,
        "final_price": final_price
    }


def create_booking_sync(
    sku_id: str,
    plan_code: str,
    quantity: int,
    promo_code: Optional[str],
    final_price: float,
    idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Synchronous validation and creation of booking record.
    POST /api/bookings
    """
    # Validation 1: SKU existence
    if sku_id not in CATALOG:
        raise ValueError(f"SKU '{sku_id}' not found in catalog")
    sku_data = CATALOG[sku_id]

    # Validation 2: Plan code
    if plan_code not in sku_data["plans"]:
        raise ValueError(f"Plan '{plan_code}' is invalid for {sku_data['name']}. Available: {list(sku_data['plans'].keys())}")

    # Validation 3: Quantity
    if quantity <= 0:
        raise ValueError("Quantity must be a positive integer (> 0)")

    # Validation 4: Promo code strict adherence
    if promo_code not in VALID_PROMO_CODES:
        raise ValueError(f"Unauthorized promo code: '{promo_code}'. Only None, 'SAVE10', 'CLOSENOW15' are permitted.")

    # Validation 5: Math integrity
    expected_quote = calculate_price(sku_id, plan_code, quantity, promo_code)
    if abs(final_price - expected_quote["final_price"]) > 0.05:
        raise ValueError(
            f"Price mismatch: provided final_price ${final_price:.2f}, expected ${expected_quote['final_price']:.2f}"
        )

    # Idempotency check: if already booked with this idempotency key, return existing record
    if idempotency_key:
        for b in BOOKINGS.values():
            if b.get("idempotency_key") == idempotency_key:
                return b

    booking_id = f"BKG-{uuid.uuid4().hex[:6].upper()}"
    record = {
        "booking_id": booking_id,
        "status": "CONFIRMED",
        "sku_id": sku_id,
        "product_name": sku_data["name"],
        "plan_code": plan_code,
        "quantity": quantity,
        "promo_code": promo_code,
        "unit_price": expected_quote["unit_price"],
        "base_price": expected_quote["base_price"],
        "discount_pct": expected_quote["discount_pct"],
        "final_price": final_price,
        "idempotency_key": idempotency_key,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    }
    BOOKINGS[booking_id] = record

    GLOBAL_API_CALL_LOGS.append({
        "api": "POST /api/bookings",
        "function": "create_booking",
        "payload": {
            "sku_id": sku_id,
            "plan_code": plan_code,
            "quantity": quantity,
            "promo_code": promo_code,
            "final_price": final_price
        },
        "response": record,
        "timestamp": time.time()
    })
    return record


async def create_booking(
    sku_id: str,
    plan_code: str,
    quantity: int,
    promo_code: Optional[str],
    final_price: float,
    idempotency_key: Optional[str] = None,
    simulate_delay: bool = True
) -> Dict[str, Any]:
    """
    POST API — Create the final booking after discussing with the user.
    Simulates ~1.2s API latency as described in Scenario 4.
    """
    if simulate_delay:
        await asyncio.sleep(1.2)

    return create_booking_sync(
        sku_id=sku_id,
        plan_code=plan_code,
        quantity=quantity,
        promo_code=promo_code,
        final_price=final_price,
        idempotency_key=idempotency_key
    )
