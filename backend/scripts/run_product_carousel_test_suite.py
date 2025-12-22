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
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"\s+", " ", t.strip().lower())
    return t


def _get_attr(item: Dict[str, Any], key: str) -> Any:
    if key in item:
        return item.get(key)
    attrs = item.get("attributes")
    if isinstance(attrs, dict):
        return attrs.get(key)
    return None


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
    expected = (test.get("expected") or {}).get("product_carousel") or {}

    data = _call_chat(
        api_url,
        user_id=user_id,
        message=user_message,
        conversation_id=conversation_id,
        timeout_seconds=timeout_seconds,
    )

    carousel = data.get("product_carousel", []) or []
    reply_text = data.get("reply_text", "") or ""

    present_expected: Optional[bool] = expected.get("present")
    min_items: int = int(expected.get("min_items") or 0)
    max_items: Optional[int] = expected.get("max_items")
    if max_items is not None:
        max_items = int(max_items)

    must_include_skus = expected.get("must_include_skus") or []
    if not isinstance(must_include_skus, list):
        must_include_skus = []

    all_items_should_match = expected.get("all_items_should_match") or {}
    if not isinstance(all_items_should_match, dict):
        all_items_should_match = {}

    got_skus = [str(p.get("sku", "")).strip() for p in carousel if isinstance(p, dict)]
    got_skus_norm = {_norm(s) for s in got_skus if s}

    res: Dict[str, Any] = {
        "id": test.get("id"),
        "pass": True,
        "user_message": user_message,
        "carousel_len": len(carousel),
        "reply_preview": reply_text[:200],
        "skus": got_skus[:15],
        "checks": [],
    }

    # Presence / size checks
    if present_expected is True and len(carousel) == 0:
        res["pass"] = False
        res["checks"].append("FAIL: expected product_carousel present but got empty")
    if present_expected is False and len(carousel) != 0:
        res["pass"] = False
        res["checks"].append("FAIL: expected product_carousel absent but got items")

    if len(carousel) < min_items:
        res["pass"] = False
        res["checks"].append(f"FAIL: expected at least {min_items} items, got {len(carousel)}")
    if max_items is not None and len(carousel) > max_items:
        res["pass"] = False
        res["checks"].append(f"FAIL: expected at most {max_items} items, got {len(carousel)}")

    # SKU inclusion checks
    for sku in must_include_skus:
        if _norm(sku) not in got_skus_norm:
            res["pass"] = False
            res["checks"].append(f"FAIL: missing expected sku={sku!r}")

    # Attribute match checks (all items)
    for k, v in all_items_should_match.items():
        expected_val = _norm(v)
        for idx, item in enumerate(carousel):
            if not isinstance(item, dict):
                continue
            actual_val = _norm(_get_attr(item, k))
            if expected_val and actual_val != expected_val:
                res["pass"] = False
                res["checks"].append(
                    f"FAIL: item[{idx}] {k}={_get_attr(item, k)!r} != expected {v!r}"
                )
                break

    if not res["checks"]:
        res["checks"].append("OK")
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Run product carousel test suite JSON against /api/v1/chat.")
    parser.add_argument(
        "--suite",
        default=str(Path(__file__).resolve().parents[1] / "tests" / "product_carousel_test.json"),
        help="Path to product_carousel_test.json",
    )
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1/chat", help="Chat API URL")
    parser.add_argument("--user-id", default="eval_product_carousel_suite", help="user_id to send")
    parser.add_argument("--conversation-id", type=int, default=0, help="conversation_id to send")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    parser.add_argument("--report", default="product_carousel_suite_report.json", help="Output report JSON filename")
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
        print(f"[{status}] {test_id} carousel={res.get('carousel_len')}")
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

