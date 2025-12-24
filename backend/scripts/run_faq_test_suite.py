import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


def _norm(text: str) -> str:
    if text is None:
        return ""
    t = str(text)
    # Normalize common punctuation to improve matching across platforms/models
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"\s+", " ", t.strip().lower())
    return t


def _contains_any(haystack: str, needles: List[str]) -> bool:
    h = _norm(haystack)
    for n in needles:
        if _norm(n) and _norm(n) in h:
            return True
    return False


def _contains_none(haystack: str, needles: List[str]) -> bool:
    h = _norm(haystack)
    for n in needles:
        nn = _norm(n)
        if nn and nn in h:
            return False
    return True


def _load_suite(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _call_chat(
    api_url: str,
    *,
    user_id: str,
    message: str,
    conversation_id: int,
    timeout_seconds: float,
) -> Dict[str, Any]:
    payload = {"user_id": user_id, "message": message, "conversation_id": conversation_id}
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
    query = test.get("query", "")
    reply = ""
    intent = ""
    sources: List[Dict[str, Any]] = []

    data = _call_chat(
        api_url,
        user_id=user_id,
        message=query,
        conversation_id=conversation_id,
        timeout_seconds=timeout_seconds,
    )
    reply = data.get("reply_text", "") or ""
    intent = data.get("intent", "") or ""
    sources = data.get("sources", []) or []

    titles = " | ".join([str(s.get("title", "")) for s in sources])
    urls = " | ".join([str(s.get("url", "")) for s in sources])
    combined = f"{reply}\n{titles}\n{urls}"

    must_include_any = test.get("must_include_any", []) or []
    must_not_include_any = test.get("must_not_include_any", []) or []

    res: Dict[str, Any] = {
        "id": test.get("id"),
        "category": test.get("category"),
        "pass": True,
        "checks": [],
        "intent": intent,
        "num_sources": len(sources),
        "reply_preview": reply[:240],
    }

    # Must include (any)
    if must_include_any:
        if not _contains_any(combined, must_include_any):
            res["pass"] = False
            res["checks"].append(f"FAIL: missing any of must_include_any={must_include_any}")
        else:
            res["checks"].append("OK: contains one of must_include_any")

    # Must not include (any)
    if must_not_include_any:
        if not _contains_none(combined, must_not_include_any):
            res["pass"] = False
            res["checks"].append(f"FAIL: contains forbidden must_not_include_any={must_not_include_any}")
        else:
            res["checks"].append("OK: does not contain must_not_include_any")

    # Soft check: sources present
    if len(sources) == 0:
        res["checks"].append("WARN: no sources returned")
    else:
        res["checks"].append("OK: sources returned")

    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Run acha_faq_test_suite.json against /api/v1/chat.")
    parser.add_argument(
        "--suite",
        default=str(Path(__file__).resolve().parents[1] / "acha_faq_test_suite.json"),
        help="Path to test suite JSON file",
    )
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1/chat", help="Chat API URL")
    parser.add_argument("--user-id", default="eval_suite_bot", help="user_id to send")
    parser.add_argument("--conversation-id", type=int, default=0, help="conversation_id to send")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    parser.add_argument("--report", default="faq_suite_report.json", help="Output report JSON filename")
    args = parser.parse_args()

    suite_path = Path(args.suite)
    suite = _load_suite(suite_path)
    tests = suite.get("tests", []) or []
    if not isinstance(tests, list) or not tests:
        raise SystemExit(f"No tests found in suite: {suite_path}")

    print(f"Suite: {suite.get('suite_name', suite_path.name)} (tests={len(tests)})")
    print(f"API: {args.api_url}\n")

    results: List[Dict[str, Any]] = []
    passed = 0

    for t in tests:
        print(f"Running id={t.get('id')}...", flush=True)
        try:
            res = _run_one(
                args.api_url,
                user_id=args.user_id,
                conversation_id=args.conversation_id,
                timeout_seconds=float(args.timeout),
                test=t,
            )
        except requests.RequestException as e:
            print(f"[ERROR] Request failed for id={t.get('id')}: {e}")
            print("Make sure the backend server is running: `cd backend; uvicorn app.main:app --reload --port 8000`")
            sys.exit(2)
        except Exception as e:
            res = {
                "id": t.get("id"),
                "category": t.get("category"),
                "pass": False,
                "checks": [f"ERROR: {e}"],
                "intent": "",
                "num_sources": 0,
                "reply_preview": "",
            }

        results.append(res)
        status = "PASS" if res["pass"] else "FAIL"
        print(f"[{status}] {res.get('id')} ({res.get('category')}) intent={res.get('intent')!r} sources={res.get('num_sources')}")
        for c in res.get("checks", []):
            print("  -", c)
        print("  reply:", res.get("reply_preview", ""))
        print()
        if res["pass"]:
            passed += 1

    out = {
        "suite": suite.get("suite_name"),
        "version": suite.get("version"),
        "api_url": args.api_url,
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    Path(args.report).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Summary: {passed}/{len(results)} passed")
    print(f"Report: {Path(args.report).resolve()}")

    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
