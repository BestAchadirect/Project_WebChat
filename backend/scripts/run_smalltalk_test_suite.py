import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


def _call_chat(api_url: str, *, user_id: str, message: str, conversation_id: int, timeout_seconds: float) -> Dict[str, Any]:
    payload = {"user_id": user_id, "message": message, "conversation_id": conversation_id, "locale": "en-US"}
    r = requests.post(api_url, json=payload, timeout=timeout_seconds)
    r.raise_for_status()
    return r.json()


def _run_one(
    api_url: str,
    *,
    user_id: str,
    conversation_id: int,
    timeout_seconds: float,
    test: Dict[str, Any],
) -> Dict[str, Any]:
    user_message = test.get("user_message") or ""
    expected = test.get("expected") or {}

    data = _call_chat(
        api_url,
        user_id=user_id,
        message=user_message,
        conversation_id=conversation_id,
        timeout_seconds=timeout_seconds,
    )

    intent = data.get("intent")
    carousel = data.get("product_carousel") or []
    sources = data.get("sources") or []
    reply_text = data.get("reply_text") or ""
    debug = data.get("debug") or {}

    checks: List[str] = []
    ok = True

    expected_intent: Optional[str] = expected.get("intent")
    if expected_intent is not None:
        if intent != expected_intent:
            ok = False
            checks.append(f"intent expected={expected_intent} got={intent}")

    expected_intent_not: Optional[str] = expected.get("intent_not")
    if expected_intent_not is not None:
        if intent == expected_intent_not:
            ok = False
            checks.append(f"intent_not violated: {expected_intent_not}")

    pc_max = expected.get("product_carousel_max")
    if pc_max is not None:
        if len(carousel) > int(pc_max):
            ok = False
            checks.append(f"product_carousel len={len(carousel)} > {pc_max}")

    pc_min = expected.get("product_carousel_min")
    if pc_min is not None:
        if len(carousel) < int(pc_min):
            ok = False
            checks.append(f"product_carousel len={len(carousel)} < {pc_min}")

    src_max = expected.get("sources_max")
    if src_max is not None:
        if len(sources) > int(src_max):
            ok = False
            checks.append(f"sources len={len(sources)} > {src_max}")

    if not reply_text.strip():
        ok = False
        checks.append("reply_text empty")

    must_contain = expected.get("reply_must_contain") or []
    if isinstance(must_contain, str):
        must_contain = [must_contain]
    if isinstance(must_contain, list) and must_contain:
        lowered = reply_text.lower()
        for token in must_contain:
            if isinstance(token, str) and token.strip():
                if token.lower() not in lowered:
                    ok = False
                    checks.append(f"reply missing token: {token}")

    expected_debug = expected.get("debug") or {}
    if isinstance(expected_debug, dict) and expected_debug:
        for key, val in expected_debug.items():
            if debug.get(key) != val:
                ok = False
                checks.append(f"debug {key} expected={val!r} got={debug.get(key)!r}")

    if not checks:
        checks.append("OK")

    return {
        "id": test.get("id"),
        "pass": ok,
        "user_message": user_message,
        "intent": intent,
        "product_carousel_len": len(carousel),
        "sources_len": len(sources),
        "reply_preview": reply_text[:160],
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run smalltalk/fallback suite JSON against /api/v1/chat.")
    parser.add_argument(
        "--suite",
        default=str(Path(__file__).resolve().parents[1] / "tests" / "smalltalk_test.json"),
        help="Path to smalltalk_test.json",
    )
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1/chat", help="Chat API URL")
    parser.add_argument("--user-id", default="eval_smalltalk_suite", help="user_id to send")
    parser.add_argument("--conversation-id", type=int, default=0, help="conversation_id to send")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    parser.add_argument("--report", default="smalltalk_suite_report.json", help="Output report JSON filename")
    args = parser.parse_args()

    suite_path = Path(args.suite)
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    tests = suite.get("tests", []) or []
    if not isinstance(tests, list) or not tests:
        raise SystemExit(f"No tests found in suite: {suite_path}")

    print(f"Suite: {suite_path} (tests={len(tests)})")
    print(f"API: {args.api_url}\n")

    results: List[Dict[str, Any]] = []
    passed = 0
    for t in tests:
        test_id = t.get("id")
        print(f"Running id={test_id}...", flush=True)
        try:
            res = _run_one(
                args.api_url,
                user_id=args.user_id,
                conversation_id=args.conversation_id,
                timeout_seconds=float(args.timeout),
                test=t,
            )
        except requests.RequestException as e:
            res = {"id": test_id, "pass": False, "checks": [f"ERROR: request failed: {e}"]}
        except Exception as e:
            res = {"id": test_id, "pass": False, "checks": [f"ERROR: {e}"]}

        results.append(res)
        status = "PASS" if res.get("pass") else "FAIL"
        print(f"[{status}] {test_id} intent={res.get('intent')} carousel={res.get('product_carousel_len')}")
        for c in res.get("checks", []):
            print("  -", c)
        if res.get("reply_preview"):
            print("  reply:", res["reply_preview"])
        print()
        if res.get("pass"):
            passed += 1

    out = {"passed": passed, "total": len(results), "results": results}
    Path(args.report).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Summary: {passed}/{len(results)} passed")
    print(f"Report: {Path(args.report).resolve()}")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
