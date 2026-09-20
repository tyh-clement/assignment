"""Command-line entry point: interactive REPL by default, or --jsonl for the
scripted evaluation adapter (one JSON object in, one JSON object out, per line)."""
from __future__ import annotations

import argparse
import json
import sys
import uuid

from dotenv import load_dotenv

from ..agent.graph import run_turn


def run_interactive() -> None:
    session_id = str(uuid.uuid4())
    print(f"OrbitMesh Support Assistant (session {session_id}). Type 'exit' to quit.", file=sys.stderr)
    while True:
        try:
            message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            break
        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            break
        result = run_turn(session_id, message)
        print(f"bot> {result['response']}")
        if result.get("citations"):
            cites = "; ".join(f"{c['source_id']} ({c['locator']})" for c in result["citations"])
            print(f"     [sources: {cites}]", file=sys.stderr)
        print(f"     [action: {result['action']}]", file=sys.stderr)


def run_jsonl() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            session_id = payload["session_id"]
            message = payload["message"]
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"[chat] malformed input line skipped: {exc}", file=sys.stderr)
            sys.stdout.write(
                json.dumps(
                    {
                        "response": "Invalid JSONL request: expected session_id and message.",
                        "citations": [],
                        "action": "ask",
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        result = run_turn(session_id, message)
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="OrbitMesh support chatbot CLI")
    parser.add_argument("--jsonl", action="store_true", help="Read/write JSONL on stdin/stdout")
    args = parser.parse_args()
    if args.jsonl:
        run_jsonl()
    else:
        run_interactive()


if __name__ == "__main__":
    main()
