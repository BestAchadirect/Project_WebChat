import json
import re
import sys
import requests
from typing import List, Dict, Any

API_URL = "http://localhost:8000/api/v1/chat"

# Edit this to match your system’s expected sources
TESTS: List[Dict[str, Any]] = [
    {
        "name": "Contact Acha",
        "message": "How can I contact Acha?",
        "should_have_sources": True,
        "must_include_any": ["achadirect", "sales@", "contact", "+66"],  # keywords expected in answer OR source
        "expected_source_title_contains": ["FAQ", "Acha"],              # based on your KnowledgeSource.title
    },
    {
        "name": "Return policy",
        "message": "What is your return policy?",
        "should_have_sources": True,
        "must_include_any": ["return", "refund", "exchange"],
        "expected_source_title_contains": ["FAQ", "policy", "Acha"],
    },
    {
        "name": "No match should fail-closed",
        "message": "What is the warranty for a spaceship engine?",
        "should_have_sources": False,
        "expect_fail_closed": True,
        "fail_closed_phrases": ["don't have enough", "do not have enough", "not enough info"],
    },
]

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def contains_any(text: str, keywords: List[str]) -> bool:
    t = norm(text)
    return any(norm(k) in t for k in keywords)

def run_test(t: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "user_id": "eval_bot",
        "message": t["message"],
        # include conversation_id if your API requires it; else remove
        "conversation_id": 0
    }

    r = requests.post(API_URL, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()

    reply = data.get("reply_text", "")
    sources = data.get("sources", []) or []
    titles = " | ".join([str(s.get("title", "")) for s in sources])
    urls = " | ".join([str(s.get("url", "")) for s in sources])
    combined = f"{reply}\n{titles}\n{urls}"

    results = {
        "name": t["name"],
        "pass": True,
        "checks": [],
        "reply_preview": reply[:200],
        "num_sources": len(sources),
    }

    # 1) sources presence
    if t.get("should_have_sources") is True and len(sources) == 0:
        results["pass"] = False
        results["checks"].append("FAIL: expected sources but got none")
    elif t.get("should_have_sources") is False and len(sources) > 0:
        results["pass"] = False
        results["checks"].append("FAIL: expected no sources but got some")
    else:
        results["checks"].append("OK: source presence")

    # 2) keyword check (reply or sources)
    if t.get("must_include_any"):
        if not contains_any(combined, t["must_include_any"]):
            results["pass"] = False
            results["checks"].append(f"FAIL: missing expected keywords {t['must_include_any']}")
        else:
            results["checks"].append("OK: contains expected keyword(s)")

    # 3) expected source title contains
    if t.get("expected_source_title_contains") and len(sources) > 0:
        if not contains_any(titles, t["expected_source_title_contains"]):
            results["pass"] = False
            results["checks"].append(f"FAIL: source title not matching {t['expected_source_title_contains']}")
        else:
            results["checks"].append("OK: source title matches")

    # 4) fail-closed behavior
    if t.get("expect_fail_closed"):
        phrases = t.get("fail_closed_phrases", [])
        if not contains_any(reply, phrases):
            results["pass"] = False
            results["checks"].append("FAIL: expected fail-closed reply but got something else")
        else:
            results["checks"].append("OK: fail-closed reply")

    return results

def main():
    print(f"Running {len(TESTS)} tests against {API_URL}\n")
    passed = 0
    all_results = []
    for t in TESTS:
        res = run_test(t)
        all_results.append(res)
        status = "PASS" if res["pass"] else "FAIL"
        print(f"[{status}] {res['name']}  (sources={res['num_sources']})")
        for c in res["checks"]:
            print("  -", c)
        print("  reply:", res["reply_preview"])
        print()
        if res["pass"]:
            passed += 1

    print(f"Summary: {passed}/{len(TESTS)} passed")
    # Optional: write JSON report
    with open("eval_report.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    if passed != len(TESTS):
        sys.exit(1)

if __name__ == "__main__":
    main()
