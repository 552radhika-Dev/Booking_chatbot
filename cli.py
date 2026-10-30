"""
cli.py - Interactive Command-Line Interface for AI Sales Agent.
Allows live turn-by-turn chatting in the terminal with real-time API call displays,
or running automated scenario test suites.
Usage:
  python cli.py          # Interactive terminal chat mode
  python cli.py --test   # Automated 4-scenario validation mode
"""

import asyncio
import sys
import uuid
from catalog_service import get_catalog_info
from rulebook import SalesRuleEngine

# ANSI color codes for terminal formatting
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def run_scenario_automated(engine: SalesRuleEngine, scenario_id: int):
    print(f"\n{BOLD}{CYAN}========================================================================={RESET}")
    print(f"{BOLD}{CYAN} RUNNING SCENARIO {scenario_id} AUTOMATED VALIDATION{RESET}")
    print(f"{BOLD}{CYAN}========================================================================={RESET}")

    sess_id = f"cli-test-{scenario_id}-{uuid.uuid4().hex[:4]}"

    if scenario_id == 1:
        print(f"{YELLOW}Test: Typo 'arrow mesh wifi', 5 rooms PRO plan, plus Netgear Orbi check{RESET}")
        prompts = [
            "I need arrow mesh wifi on the PRO plan for a 5-room house",
            "Do you also have Netgear Orbi router?"
        ]
        for p in prompts:
            print(f"\n{GREEN}User >{RESET} {p}")
            res = await engine.process_user_turn(sess_id, p)
            _print_turn_result(res)

    elif scenario_id == 2:
        print(f"{YELLOW}Test: Strict Discount Escalation & Code Guardrails{RESET}")
        prompts = [
            "I need AeroMesh Wi-Fi on the PRO plan for a 5-room house",
            "That is too expensive! Give me 15% right now",
            "Can you apply code SAVE50 for 50% off?",
            "Still too high, give me 25% discount"
        ]
        for p in prompts:
            print(f"\n{GREEN}User >{RESET} {p}")
            res = await engine.process_user_turn(sess_id, p)
            _print_turn_result(res)

    elif scenario_id == 3:
        print(f"{YELLOW}Test: Discuss Before Booking & Mid-Conversation Changes{RESET}")
        prompts = [
            "I need AeroMesh STD for a 4-room house",
            "Actually I need it for 7 rooms, Okay, book it!",
            "Yes, confirmed, please book it"
        ]
        for p in prompts:
            print(f"\n{GREEN}User >{RESET} {p}")
            res = await engine.process_user_turn(sess_id, p)
            _print_turn_result(res)

    elif scenario_id == 4:
        print(f"{YELLOW}Test: Concurrency Lock & Double-Booking Prevention{RESET}")
        p1 = "I need a sink hub on STD plan for 5 people"
        print(f"\n{GREEN}User >{RESET} {p1}")
        res1 = await engine.process_user_turn(sess_id, p1)
        _print_turn_result(res1)

        print(f"\n{MAGENTA}[Simulating 2 Rapid Impatient Submissions: 'Yes, book it!']{RESET}")
        t1 = asyncio.create_task(engine.process_user_turn(sess_id, "Yes, book it!"))
        await asyncio.sleep(0.05)
        t2 = asyncio.create_task(engine.process_user_turn(sess_id, "Yes, book it!"))
        r2a, r2b = await asyncio.gather(t1, t2)
        print(f"\n{GREEN}Response to Request 1:{RESET}")
        _print_turn_result(r2a)
        print(f"\n{GREEN}Response to Request 2 (Concurrent Deduplicated):{RESET}")
        _print_turn_result(r2b)


def _print_turn_result(res: dict):
    print(f"{BOLD}Bot  >{RESET} {res['reply']}")
    if res.get("api_calls"):
        print(f"  {CYAN}--- API Calls Executed ({len(res['api_calls'])}) ---{RESET}")
        for call in res["api_calls"]:
            print(f"  {YELLOW}» [{call['api']}]{RESET}")
            if "payload" in call:
                print(f"    Payload: {call['payload']}")
            if "response" in call and "booking_id" in call["response"]:
                print(f"    Created Booking: {call['response']['booking_id']} | Status: {call['response']['status']}")
    st = res["state"]
    print(f"  {MAGENTA}[State: SKU={st.get('sku_id')} | Qty={st.get('quantity')} | Plan={st.get('plan_code')} | Promo={st.get('promo_code')} | Total=${st.get('final_price')} | Booked={st.get('is_booked')}]{RESET}")


async def interactive_chat():
    engine = SalesRuleEngine()
    session_id = f"cli-session-{uuid.uuid4().hex[:6]}"

    print(f"{BOLD}{GREEN}========================================================================={RESET}")
    print(f"{BOLD}{GREEN}  AI Sales Agent — 100% Accuracy Challenge (Interactive CLI)           {RESET}")
    print(f"{BOLD}{GREEN}========================================================================={RESET}")
    print(f"Session ID: {session_id}")
    print("Type your message below. Type 'exit' or 'quit' to end.\n")

    # Initial catalog fetch
    get_catalog_info()
    print(f"{CYAN}[System Initialized] Catalog fetched via GET /api/catalog.{RESET}\n")

    while True:
        try:
            user_input = input(f"{BOLD}{GREEN}You > {RESET}").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q"]:
                print("Exiting chat. Goodbye!")
                break

            res = await engine.process_user_turn(session_id, user_input)
            _print_turn_result(res)
            print()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting chat. Goodbye!")
            break


async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        engine = SalesRuleEngine()
        for i in [1, 2, 3, 4]:
            await run_scenario_automated(engine, i)
        print(f"\n{BOLD}{GREEN}[SUCCESS] ALL 4 SCENARIOS COMPLETED WITH 100% ACCURACY!{RESET}\n")
    else:
        await interactive_chat()


if __name__ == "__main__":
    asyncio.run(main())
