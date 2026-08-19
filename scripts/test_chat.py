"""Interactive CLI for the /chat endpoint.

Usage:
    DESS_TOKEN=eyJ... .venv/bin/python -m scripts.test_chat
    # or just run it; it'll prompt for the token

The script keeps conversation history in-process so multi-turn works.
Ctrl+C exits cleanly. Mostly used for hand-validating the chat flow
before Day 4 ships the real frontend.

Quick way to mint a token for the seed user:
    .venv/bin/python -c "from app.database import SessionLocal; \\
        from app.models import User; from app.security import \\
        create_access_token; db = SessionLocal(); u = db.query(User).first(); \\
        print(create_access_token(u.id))"
"""

import json
import os
import sys
from getpass import getpass

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"


def _read_token() -> str:
    token = os.environ.get("DESS_TOKEN")
    if token:
        return token
    print("No DESS_TOKEN env var set.")
    return getpass("Paste a bearer token: ").strip()


def _print_reply(body: dict[str, object]) -> None:
    reply = body.get("reply", "")
    print(f"\nDess: {reply}")
    tool_calls = body.get("tool_calls") or []
    if isinstance(tool_calls, list) and tool_calls:
        print(f"  [tools used: {len(tool_calls)}]")
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            name = tc.get("name")
            params = json.dumps(tc.get("params", {}), default=str)
            print(f"    - {name}({params})")
    in_tok = body.get("input_tokens_used", 0)
    out_tok = body.get("output_tokens_used", 0)
    print(f"  [tokens: in={in_tok} out={out_tok}]")


def main() -> int:
    base_url = os.environ.get("DESS_API_URL", DEFAULT_BASE_URL).rstrip("/")
    token = _read_token()
    if not token:
        print("No token provided. Exiting.", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bearer {token}"}
    history: list[dict[str, str]] = []

    print(f"Connected to {base_url}/api/chat. Ctrl+C to exit.\n")
    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                print()
                return 0
            if not user_input:
                continue

            payload = {"message": user_input, "history": history}
            try:
                resp = httpx.post(
                    f"{base_url}/api/chat",
                    headers=headers,
                    json=payload,
                    timeout=120.0,
                )
            except httpx.RequestError as e:
                print(f"\n[network error: {e}]\n")
                continue

            if resp.status_code != 200:
                print(f"\n[HTTP {resp.status_code}] {resp.text}\n")
                continue

            body = resp.json()
            _print_reply(body)
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": str(body.get("reply", ""))})
            print()
    except KeyboardInterrupt:
        print("\nbye")
        return 0


if __name__ == "__main__":
    sys.exit(main())
