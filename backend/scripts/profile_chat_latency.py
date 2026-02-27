from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.schemas.chat import ChatRequest
from app.services.chat.service import ChatService
from app.utils.debug_log import DEBUG_LOG_PATH


DEFAULT_PROMPTS = [
    "Show me titanium barbells in stock",
    "What is the price and stock for SKU BILBP2-F02A07?",
    "Do you have black labret jewelry?",
    "Show image of black barbell 25mm",
    "What gauge options are available for circular barbells?",
    "Can I get shipping policy details?",
    "Compare return policy and exchange policy",
    "Find rose gold nose ring products",
    "I need threadless labret tops in stock",
    "Show similar in-stock items for opal barbell",
    "Do you have product code AB-123?",
    "Need material details for titanium G23 barbell",
    "Tell me if SKU XYZ-001 is available",
    "Browse products for black rings",
    "What is your minimum order quantity policy?",
    "Show barbell attachments",
    "Any image for SKU BILBP2-F02A07",
    "Need product details for internal threading options",
    "Can I sample your products before ordering?",
    "Find in-stock labret with 1.2mm gauge",
]

STAGE_KEYS = [
    "intent_routing_ms",
    "detail_query_parser_ms",
    "retrieval_gate_ms",
    "vector_search_ms",
    "db_product_lookup_ms",
    "llm_parse_ms",
    "llm_answer_ms",
    "response_build_ms",
    "total_ms",
]


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    rank = int(math.ceil((p / 100.0) * len(ordered))) - 1
    rank = max(0, min(rank, len(ordered) - 1))
    return ordered[rank]


def summarize(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"avg": 0.0, "p50": 0.0, "p95": 0.0}
    avg = sum(values) / len(values)
    return {
        "avg": round(avg, 2),
        "p50": round(percentile(values, 50), 2),
        "p95": round(percentile(values, 95), 2),
    }


def parse_db_host(database_url: str) -> str:
    normalized = (database_url or "").replace("postgresql+asyncpg://", "postgresql://")
    if not normalized:
        return "unknown"
    try:
        parsed = urlparse(normalized)
        host = parsed.hostname or ""
        port = parsed.port
        if host and port:
            return f"{host}:{port}"
        if host:
            return host
    except Exception:
        pass

    # Fallback for non-url-escaped credentials (e.g., ':' or '@' in password)
    tail = normalized.rsplit("@", 1)[-1] if "@" in normalized else normalized.split("://", 1)[-1]
    host_port = tail.split("/", 1)[0].strip()
    if not host_port:
        return "unknown"
    if ":" in host_port:
        host, maybe_port = host_port.rsplit(":", 1)
        host = host.strip() or host_port
        if maybe_port.isdigit():
            return f"{host}:{maybe_port}"
        return host
    return host_port


def parse_vector_location(database_url: str) -> str:
    host = parse_db_host(database_url)
    return f"pgvector on {host}" if host != "unknown" else "unknown"


def load_prompts(path: Optional[str], count: int) -> List[str]:
    if path:
        raw = Path(path).read_text(encoding="utf-8")
        prompts = [line.strip() for line in raw.splitlines() if line.strip()]
        if prompts:
            return prompts[:count]
    if count <= len(DEFAULT_PROMPTS):
        return DEFAULT_PROMPTS[:count]
    repeats = (count // len(DEFAULT_PROMPTS)) + 1
    return (DEFAULT_PROMPTS * repeats)[:count]


def read_new_latency_event(path: Path, offset: int) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            lines = fh.read().splitlines()
    except Exception:
        return None

    latency_event: Optional[Dict[str, Any]] = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        location = str(payload.get("location") or "")
        if location in {"chat_service.latency_spans", "chat_service.latency_spans.error"}:
            latency_event = payload
    return latency_event


def normalize_latency_event(event: Optional[Dict[str, Any]], external_total_ms: float) -> Dict[str, Any]:
    base = {
        "total_ms": round(float(external_total_ms), 2),
        "intent_routing_ms": 0.0,
        "detail_mode_triggered": False,
        "detail_query_parser_ms": 0.0,
        "retrieval_gate_ms": 0.0,
        "vector_search_ms": 0.0,
        "db_product_lookup_ms": 0.0,
        "tickets_service_ms": 0.0,
        "llm_calls_count": 0,
        "llm_parse_ms": 0.0,
        "llm_answer_ms": 0.0,
        "response_build_ms": 0.0,
        "_event_found": False,
        "_error": None,
    }
    if not event:
        return base

    location = str(event.get("location") or "")
    data = event.get("data") or {}
    spans = data.get("latency_spans") if location.endswith(".error") else data
    if not isinstance(spans, dict):
        return base

    result = dict(base)
    result["_event_found"] = True
    if location.endswith(".error"):
        result["_error"] = data.get("error")
    for key in list(result.keys()):
        if key.startswith("_"):
            continue
        value = spans.get(key, result[key])
        if isinstance(result[key], bool):
            result[key] = bool(value)
        elif key == "llm_calls_count":
            try:
                result[key] = int(value or 0)
            except Exception:
                result[key] = 0
        else:
            try:
                result[key] = round(float(value or 0.0), 2)
            except Exception:
                result[key] = 0.0

    if result["total_ms"] <= 0:
        result["total_ms"] = round(float(external_total_ms), 2)
    return result


async def run_profile(prompts: List[str], user_prefix: str) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    debug_path = Path(DEBUG_LOG_PATH)
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    if not debug_path.exists():
        debug_path.touch()

    async with AsyncSessionLocal() as db:
        service = ChatService(db)
        for idx, prompt in enumerate(prompts, start=1):
            file_offset = debug_path.stat().st_size if debug_path.exists() else 0
            started = time.perf_counter()
            error: Optional[str] = None
            response_debug: Dict[str, Any] = {}
            try:
                req = ChatRequest(
                    user_id=f"{user_prefix}-{idx % 4}",
                    message=prompt,
                    locale="en-US",
                )
                response = await service.process_chat(req, channel="widget")
                response_debug = dict(getattr(response, "debug", {}) or {})
            except Exception as exc:
                error = str(exc)
                try:
                    await db.rollback()
                except Exception:
                    pass
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            event = read_new_latency_event(debug_path, file_offset)
            spans = normalize_latency_event(event, elapsed_ms)
            results.append(
                {
                    "idx": idx,
                    "prompt": prompt,
                    "success": error is None,
                    "exception": error,
                    "spans": spans,
                    "debug": response_debug,
                }
            )

    totals = [row["spans"]["total_ms"] for row in results]
    stage_summary: Dict[str, Dict[str, float]] = {}
    for key in STAGE_KEYS:
        values = [float(row["spans"].get(key, 0.0) or 0.0) for row in results]
        stage_summary[key] = summarize(values)

    llm_calls = [int(row["spans"].get("llm_calls_count", 0) or 0) for row in results]
    detail_hits = [1 if row["spans"].get("detail_mode_triggered") else 0 for row in results]
    event_hits = [1 if row["spans"].get("_event_found") else 0 for row in results]
    hot_cache_hits = [1 if bool((row.get("debug") or {}).get("hot_cache_hit")) else 0 for row in results]
    structured_cache_hits = [
        1 if bool((row.get("debug") or {}).get("structured_query_cache_hit")) else 0 for row in results
    ]
    semantic_cache_hits = [1 if bool((row.get("debug") or {}).get("semantic_cache_hit")) else 0 for row in results]
    network_errors = [1 if str((row.get("debug") or {}).get("network_error_type") or "").strip() else 0 for row in results]
    external_calls = [int((row.get("debug") or {}).get("external_call_count") or 0) for row in results]
    embedding_calls = [
        int(((row.get("debug") or {}).get("external_call_counts") or {}).get("embedding_query", 0) or 0)
        for row in results
    ]

    return {
        "request_count": len(results),
        "success_count": sum(1 for row in results if row["success"]),
        "failure_count": sum(1 for row in results if not row["success"]),
        "event_count": sum(event_hits),
        "summary": summarize(totals),
        "stage_summary": stage_summary,
        "llm_calls_avg": round((sum(llm_calls) / len(llm_calls)) if llm_calls else 0.0, 2),
        "embedding_calls_avg": round((sum(embedding_calls) / len(embedding_calls)) if embedding_calls else 0.0, 2),
        "external_call_count_avg": round((sum(external_calls) / len(external_calls)) if external_calls else 0.0, 2),
        "hot_cache_hit_rate": round((sum(hot_cache_hits) / len(hot_cache_hits)) if hot_cache_hits else 0.0, 3),
        "structured_query_cache_hit_rate": round(
            (sum(structured_cache_hits) / len(structured_cache_hits)) if structured_cache_hits else 0.0,
            3,
        ),
        "semantic_cache_hit_rate": round((sum(semantic_cache_hits) / len(semantic_cache_hits)) if semantic_cache_hits else 0.0, 3),
        "network_error_rate": round((sum(network_errors) / len(network_errors)) if network_errors else 0.0, 3),
        "detail_mode_rate": round((sum(detail_hits) / len(detail_hits)) if detail_hits else 0.0, 3),
        "rows": results,
    }


def build_report(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "environment": {
            "env_name": settings.ENVIRONMENT,
            "db_location": parse_db_host(settings.DATABASE_URL),
            "vector_db_location": parse_vector_location(settings.DATABASE_URL),
            "models": {
                "nlu_model": settings.NLU_MODEL,
                "answer_model": settings.RAG_ANSWER_MODEL,
                "embedding_model": settings.EMBEDDING_MODEL,
            },
            "nlu_fast_path_enabled": bool(getattr(settings, "NLU_FAST_PATH_ENABLED", True)),
        },
        "profile": profile,
    }


def print_human(report: Dict[str, Any]) -> None:
    env = report["environment"]
    profile = report["profile"]
    summary = profile["summary"]
    stage_summary = profile["stage_summary"]

    print("BASELINE SUMMARY")
    print(f"- Environment: {env['env_name']}")
    print(f"- DB location: {env['db_location']}")
    print(f"- Vector DB location: {env['vector_db_location']}")
    print(
        f"- Models: nlu={env['models']['nlu_model']}, "
        f"answer={env['models']['answer_model']}, embedding={env['models']['embedding_model']}"
    )
    print(f"- Requests: {profile['request_count']} (success={profile['success_count']}, fail={profile['failure_count']})")
    print(f"- Avg latency: {summary['avg']} ms")
    print(f"- P50: {summary['p50']} ms")
    print(f"- P95: {summary['p95']} ms")
    print(f"- LLM calls/request (avg): {profile['llm_calls_avg']}")
    print(f"- Embedding calls/request (avg): {profile['embedding_calls_avg']}")
    print(f"- External calls/request (avg): {profile['external_call_count_avg']}")
    print(f"- Hot cache hit rate: {profile['hot_cache_hit_rate']}")
    print(f"- Structured query cache hit rate: {profile['structured_query_cache_hit_rate']}")
    print(f"- Semantic cache hit rate: {profile['semantic_cache_hit_rate']}")
    print(f"- Network error rate: {profile['network_error_rate']}")
    print(f"- Detail mode rate: {profile['detail_mode_rate']}")
    print("")
    print("STAGE LATENCY (Average / P95)")
    for key in STAGE_KEYS:
        stage = stage_summary[key]
        print(f"{key}: {stage['avg']} / {stage['p95']} ms")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Profile chat latency spans.")
    parser.add_argument("--count", type=int, default=20, help="Number of requests to run.")
    parser.add_argument("--prompts-file", type=str, default=None, help="Optional text file with prompts, one per line.")
    parser.add_argument("--user-prefix", type=str, default="latency-profiler", help="User id prefix.")
    parser.add_argument("--json-out", type=str, default=None, help="Optional path to write JSON report.")
    args = parser.parse_args()

    prompts = load_prompts(args.prompts_file, max(1, int(args.count)))
    profile = await run_profile(prompts=prompts, user_prefix=args.user_prefix)
    report = build_report(profile)
    print_human(report)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        print("")
        print(f"Saved report to: {out_path}")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
