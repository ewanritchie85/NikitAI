def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()

    from .agent import run_agent

    run_agent()
