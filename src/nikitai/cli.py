from __future__ import annotations

from .agent import Agent, PendingConfirmation


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()

    run_agent()


def _confirm(pending: PendingConfirmation) -> bool:
    if pending.tool_name == "send_email":
        to = pending.tool_input.get("to", "")
        subject = pending.tool_input.get("subject", "")
        body = pending.tool_input.get("body", "")
        print(f"\nTo:      {to}\nSubject: {subject}\nBody:\n{body}\n")
        return input("Send this? [y/N] ").strip().lower() == "y"

    print(f"\n[calling {pending.tool_name} with {pending.tool_input}]\n")
    return input("Proceed? [y/N] ").strip().lower() == "y"


def run_agent() -> None:
    agent = Agent()

    print("NikitAI is ready. Type 'quit' to exit.\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"quit", "exit", "q"}:
            break
        if not user_input:
            continue

        response = agent.send(user_input)

        while response.pending is not None:
            if response.text:
                print(f"\nNikitAI: {response.text}\n")
            approved = _confirm(response.pending)
            response = agent.confirm(response.pending.id, approved)

        if response.error:
            print(f"\nNikitAI error: {response.error}\n")
        elif response.text:
            print(f"\nNikitAI: {response.text}\n")
