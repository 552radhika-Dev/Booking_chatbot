# AI Sales Agent — 100% Accuracy Challenge

An autonomous conversational sales agent built for 100% accuracy, zero hallucinations, strict discount escalation, discuss-before-booking confirmation, and thread-safe double-booking prevention.

---

## 🚀 Key Requirements & 100% Accuracy Enforcement

### 1. Scenario 1: Fetching Info & Exact Quantity Calculation
- **Informal names and typo matching**:
  - `"arrow mesh wifi"`, `"aeromesh"`, `"mesh wifi"` ➔ `SKU_MESH_WIFI6` ("AeroMesh Wi-Fi 6E Home Pack")
  - `"sink hub"`, `"synchub"`, `"conference bar"` ➔ `SKU_TEAM_HUB` ("SyncHub Conference Bar")
  - `"airpods"`, `"air pods"`, `"airpods pro"` ➔ `SKU_AIRPODS_PRO2` ("AirPods Pro 2nd Gen")
- **Capacity formula**:
  - `quantity = math.ceil(user_requirement / max_capacity_per_unit)`
  - *Example*: 5 rooms for AeroMesh (max capacity 2) ➔ $\lceil 5 / 2 \rceil = 3$ units.
  - Explains the calculation clearly during discussion.
- **Out-of-catalog items**:
  - Queries for products not in our catalog (e.g. `"Netgear Orbi router"`, `"Eero"`, `"Google Nest"`) are detected and politely rejected without ever matching or booking catalog items by mistake.

### 2. Scenario 2: Price Discussion & Strict Discount Rules
- **Standard quote first**: 0% discount, `promo_code = None`.
- **First objection**: Offers ONLY `SAVE10` (10% off).
  - Even if user demands *"Give me 15% right now"* or *"Apply code SAVE50 for 50% off"*, the agent refuses premature jumps and unauthorized promo codes, strictly enforcing `SAVE10`.
- **Second objection**: Offers `CLOSENOW15` (15% off — absolute maximum).
- **Third+ objection**: Strictly holds at 15% (`CLOSENOW15`), stating it is the rock-bottom maximum courtesy discount.
- **Unauthorized codes**: Rejects fake coupons (`SAVE50`, `FLASH50`, etc.).

### 3. Scenario 3: Discuss Before Booking & Mid-Conversation Changes
- The agent **never** calls `create_booking` until it has fetched info, clearly quoted the exact package, plan, quantity, and total price to the user, and received user confirmation.
- If the user changes any parameter (e.g. 4 rooms to 7 rooms, or switches from STD to PRO) and says *"Okay, book it!"* in the same turn:
  - The agent updates the numbers (e.g., 7 rooms ➔ 4 units @ $1596.00).
  - **Withholds booking!** It requests the user to confirm the updated quote.
  - Only upon the user's subsequent confirmation does it call `create_booking`.

### 4. Scenario 4: Interruptions & Concurrency Protection
- If a user sends *"Yes, book it!"* twice in rapid succession while `create_booking` is executing (~1.2s delay):
  - Session-level `asyncio.Lock` serializes execution.
  - Idempotency guard ensures exactly **one** booking call is executed.
  - The second request is safely deduplicated and returns the confirmed booking reference without double charging or corrupting state.

---

## 📡 Challenge APIs

### 1. GET `/api/catalog`
Returns available packages, max capacities, and plan pricing:
```json
{
  "SKU_AIRPODS_PRO2": {
    "name": "AirPods Pro 2nd Gen",
    "max_capacity_per_unit": 1,
    "plans": {"STD": 249.0, "CARE": 279.0}
  },
  "SKU_MESH_WIFI6": {
    "name": "AeroMesh Wi-Fi 6E Home Pack",
    "max_capacity_per_unit": 2,
    "plans": {"STD": 399.0, "PRO": 499.0}
  },
  "SKU_TEAM_HUB": {
    "name": "SyncHub Conference Bar",
    "max_capacity_per_unit": 3,
    "plans": {"STD": 899.0, "PRO": 1150.0}
  }
}
```

### 2. POST `/api/bookings`
Creates final booking after user confirmation:
```json
{
  "sku_id": "SKU_MESH_WIFI6",
  "plan_code": "PRO",
  "quantity": 3,
  "promo_code": "SAVE10",
  "final_price": 1347.30
}
```

---

## 🧪 Running Automated Tests

Run the full pytest suite:
```bash
pytest -v
```
All tests pass with 100% test assertion coverage.

---

## 🖥️ Running the CLI

### 1. Automated CLI Validation:
```bash
python cli.py --test
```
Runs all 4 scenarios automatically in the terminal, printing live turn-by-turn dialogues, API calls, and assertions.

### 2. Interactive Terminal Chat:
```bash
python cli.py
```
Allows manual chat in the terminal with real-time colorized API call logs.

---

## 🌐 Running the Web Application

Start the FastAPI application:
```bash
python app.py
```
Or with Uvicorn:
```bash
uvicorn app:app --port 8000 --reload
```

Open your browser at:
**`http://127.0.0.1:8000`**

### Web UI Features:
1. **Interactive Conversational UI**: Chat turn-by-turn with quick scenario chips.
2. **1-Click Automated Scenario Runner**: Single button to run and verify all 4 scenarios with visual pass badges.
3. **Live API Inspector**: Real-time collapsible cards showing request payloads and responses for `GET /api/catalog` and `POST /api/bookings`.
4. **Session Guardrails Dashboard**: Real-time telemetry tracking SKU, ceil capacity formula, discount escalation, and double-booking locks.
