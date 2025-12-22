import json
import sys
from typing import Any, Dict, List

import requests

API_URL = "http://localhost:8000/api/v1/chat"

TESTS: List[Dict[str, Any]] = [
    {
        "name": "Product query should return carousel",
        "message": "show me barbells 14g",
        "expect_carousel_min": 1,
    },
    {
        "name": "FAQ query should not return carousel",
        "message": "How can I contact Acha?",
        "expect_carousel_min": 0,
        "expect_carousel_max": 0,
    },
]


def run_one(t: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "user_id": "eval_carousel_bot",
        "message": t["message"],
        "conversation_id": 0,
        "locale": "en-US",
    }
    r = requests.post(API_URL, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()

    carousel = data.get("product_carousel", []) or []
    reply = data.get("reply_text", "") or ""

    res: Dict[str, Any] = {
        "name": t["name"],
        "pass": True,
        "carousel_len": len(carousel),
        "reply_preview": reply[:160],
        "checks": [],
    }

    min_len = int(t.get("expect_carousel_min", 0))
    max_len = t.get("expect_carousel_max")
    if len(carousel) < min_len:
        res["pass"] = False
        res["checks"].append(f"FAIL: expected carousel_len >= {min_len}, got {len(carousel)}")
    else:
        res["checks"].append("OK: carousel_min")

    if max_len is not None and len(carousel) > int(max_len):
        res["pass"] = False
        res["checks"].append(f"FAIL: expected carousel_len <= {max_len}, got {len(carousel)}")
    elif max_len is not None:
        res["checks"].append("OK: carousel_max")

    return res


def main() -> None:
    results = [run_one(t) for t in TESTS]
    passed = sum(1 for r in results if r["pass"])
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"[{status}] {r['name']} (carousel={r['carousel_len']})")
        for c in r["checks"]:
            print("  -", c)
        print("  reply:", r["reply_preview"])
        print()

    with open("eval_product_carousel_report.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"Summary: {passed}/{len(results)} passed")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()

