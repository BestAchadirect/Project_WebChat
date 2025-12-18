import os
import sys
import requests

API_URL = os.getenv("RAG_SMOKE_API_URL", "http://localhost:8000/api/v1/chat")

QUERIES = [
    "What is your minimum order?",
    "What is your return policy?",
    "What is the warranty for a spaceship engine?",
]


def main() -> int:
    print(f"RAG smoke against {API_URL}")
    ok = True
    for q in QUERIES:
        payload = {"user_id": "smoke_bot", "message": q, "conversation_id": 0}
        r = requests.post(API_URL, json=payload, timeout=60)
        if r.status_code != 200:
            print(f"FAIL {q!r}: {r.status_code} {r.text[:200]}")
            ok = False
            continue
        data = r.json()
        print(f"- q={q!r}")
        print(f"  intent={data.get('intent')} sources={len(data.get('sources') or [])}")
        print(f"  reply={str(data.get('reply_text',''))[:140]!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

