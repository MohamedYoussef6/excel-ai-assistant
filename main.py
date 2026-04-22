"""
main.py — CLI entry point.

Usage:
    python main.py                  # interactive chat loop
    python main.py --verbose        # show debug tool calls
    python main.py --query "..."    # single query and exit
"""

import argparse
import sys
import os
from dotenv import load_dotenv

load_dotenv()

from agent import Agent


WELCOME = """
╔══════════════════════════════════════════════════════════════════╗
║          Excel AI Assistant — Real Estate & Marketing            ║
╠══════════════════════════════════════════════════════════════════╣
║  Ask anything about the two Excel files in natural language.     ║
║  Examples:                                                       ║
║    • Show all 3-bedroom houses in Texas under $500,000           ║
║    • What is the average sale price by property type?            ║
║    • Add a new listing: 2-bed condo in Miami, $320k, Active      ║
║    • Update LST-5001 status to Pending                           ║
║    • Delete campaign CMP-8003                                    ║
║    • Which marketing channel has the highest average ROI?        ║
║  Commands:  'reset' — clear history | 'quit' — exit             ║
╚══════════════════════════════════════════════════════════════════╝
"""


def run_interactive(agent: Agent):
    print(WELCOME)
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if user_input.lower() == "reset":
            agent.reset()
            continue

        print("\nAssistant: ", end="", flush=True)
        response = agent.run(user_input)
        print(response)


def main():
    parser = argparse.ArgumentParser(description="Excel AI Assistant")
    parser.add_argument("--verbose", action="store_true",
                        help="Show tool call debug output")
    parser.add_argument("--query", type=str, default=None,
                        help="Run a single query and exit")
    args = parser.parse_args()

    # Validate environment
    if not os.getenv("GROQ_API_KEY") and not os.getenv("GEMINI_API_KEY"):
        print("ERROR: No API key found.")
        print("Create a .env file with GROQ_API_KEY=your_key_here")
        print("Get a free key at: https://console.groq.com")
        sys.exit(1)

    agent = Agent(verbose=args.verbose)

    if args.query:
        print(agent.run(args.query))
    else:
        run_interactive(agent)


if __name__ == "__main__":
    main()
