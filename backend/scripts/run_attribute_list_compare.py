import argparse
import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.db.session import AsyncSessionLocal
from app.services.ai.llm_service import llm_service
from app.services.catalog.product_search import CatalogProductSearchService
from app.services.chat.components.pipeline import ComponentPipeline
from app.services.chat.retrieval.follow_up_policy import extract_product_attribute_values
from app.services.chat.text_normalization import normalize_user_text


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[1] / "tests" / "regression" / "data" / "attribute_list_compare_cases.json"


def _normalize_value(value: Any) -> str:
    return normalize_user_text(str(value or ""))


def _load_cases(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"comparison dataset must be a list: {path}")
    cases: List[Dict[str, Any]] = []
    for raw_case in payload:
        case = dict(raw_case or {})
        case_id = str(case.get("id") or "").strip()
        query = str(case.get("query") or "").strip()
        target = str(case.get("target") or "").strip().lower()
        if not case_id:
            raise ValueError(f"comparison case missing id: {path}")
        if not query:
            raise ValueError(f"comparison case missing query: {case_id}")
        if not target:
            raise ValueError(f"comparison case missing target: {case_id}")
        case["id"] = case_id
        case["query"] = query
        case["target"] = target
        case["attribute_filters"] = dict(case.get("attribute_filters") or {})
        cases.append(case)
    return cases


def _score_against_reference(*, current_values: List[str], vector_values: List[str]) -> Dict[str, Any]:
    current_norm = [_normalize_value(item) for item in list(current_values or []) if _normalize_value(item)]
    vector_norm = [_normalize_value(item) for item in list(vector_values or []) if _normalize_value(item)]
    current_set = list(dict.fromkeys(current_norm))
    vector_set = list(dict.fromkeys(vector_norm))
    current_lookup = set(current_set)
    vector_lookup = set(vector_set)
    overlap = sorted(current_lookup.intersection(vector_lookup))
    current_recall = float(len(overlap) / len(current_set)) if current_set else 0.0
    vector_precision = float(len(overlap) / len(vector_set)) if vector_set else 0.0
    return {
        "current_values": current_set,
        "vector_values": vector_set,
        "overlap": overlap,
        "current_recall": round(current_recall, 4),
        "vector_precision": round(vector_precision, 4),
    }


def _attribute_list_display_label(target: str) -> str:
    target_norm = str(target or "").strip().lower()
    labels = {
        "gauge": "gauge options",
        "material": "material options",
        "jewelry_type": "jewelry type options",
        "body_part": "body part options",
        "presentation_type": "presentation type options",
        "feature": "feature options",
        "color": "color options",
        "threading": "threading options",
        "theme": "theme options",
    }
    return labels.get(target_norm, f"{target_norm.replace('_', ' ')} options" if target_norm else "available options")


def _attribute_list_scope_label(*, attribute_filters: Dict[str, str]) -> str:
    filters = dict(attribute_filters or {})
    material = str(filters.get("material") or "").strip()
    jewelry_type = str(filters.get("jewelry_type") or "").strip()
    if material and jewelry_type:
        return f"{material.lower()} {jewelry_type.lower()}"
    if material:
        return f"{material.lower()} jewelry"
    if jewelry_type:
        return jewelry_type.lower()
    return "matching products"


def _format_attribute_list_reply(*, target: str, attribute_filters: Dict[str, str], values: List[str]) -> str:
    count = len(list(values or []))
    values_text = ", ".join([str(item).strip() for item in list(values or []) if str(item).strip()])
    if count == 0:
        return "I couldn't find any matching options."
    scope_label = _attribute_list_scope_label(attribute_filters=attribute_filters)
    list_label = _attribute_list_display_label(target)
    if count == 1:
        values_text = str(values[0]).strip()
    elif count == 2:
        values_text = f"{values[0]} and {values[1]}"
    elif count > 2:
        values_text = ", ".join([str(item).strip() for item in values[:-1]]) + f", and {values[-1]}"
    if scope_label == "matching products":
        return f"I found {count} {list_label}: {values_text}."
    return f"I found {count} {list_label} for {scope_label}: {values_text}."


async def _current_system_values(*, pipeline: ComponentPipeline, query: str, target: str, attribute_filters: Dict[str, str]) -> List[str]:
    del query
    return await pipeline._load_distinct_attribute_values(  # noqa: SLF001
        target=target,
        attribute_filters=attribute_filters,
        limit=12,
    )


async def _vector_baseline_values(*, db, query: str, target: str) -> List[str]:
    query_embedding = await llm_service.generate_embedding(query)
    search = CatalogProductSearchService(db=db)
    result = await search.vector_search(
        query_embedding=list(query_embedding or []),
        limit=12,
        candidate_limit=36,
    )
    return extract_product_attribute_values(
        products=list(result.cards or []),
        key=target,
        limit=12,
    )


async def _run_case(*, db, case: Dict[str, Any]) -> Dict[str, Any]:
    query = str(case["query"])
    target = str(case["target"])
    attribute_filters = dict(case.get("attribute_filters") or {})
    pipeline = ComponentPipeline(
        db=db,
        catalog_search=SimpleNamespace(),
        knowledge_retrieval=SimpleNamespace(search=lambda *args, **kwargs: []),
        redis_cache=SimpleNamespace(),
    )
    current_values = await _current_system_values(
        pipeline=pipeline,
        query=query,
        target=target,
        attribute_filters=attribute_filters,
    )
    vector_values: List[str] = []
    vector_error = ""
    try:
        vector_values = await _vector_baseline_values(
            db=db,
            query=query,
            target=target,
        )
    except Exception as exc:
        vector_error = str(exc)
    score = _score_against_reference(current_values=current_values, vector_values=vector_values)
    score["current_reply"] = _format_attribute_list_reply(
        target=target,
        attribute_filters=attribute_filters,
        values=current_values,
    )
    score["vector_reply"] = _format_attribute_list_reply(
        target=target,
        attribute_filters=attribute_filters,
        values=vector_values,
    )
    score["id"] = str(case["id"])
    score["query"] = query
    score["target"] = target
    score["attribute_filters"] = attribute_filters
    score["vector_error"] = vector_error
    return score


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Compare current attribute-list answers against a vector-search baseline.")
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(DEFAULT_DATASET_PATH),
        help="Path to a JSON dataset of comparison cases.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full comparison payload as JSON.",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset).resolve()
    cases = _load_cases(dataset_path)

    async with AsyncSessionLocal() as db:
        results = []
        for case in cases:
            try:
                results.append(await _run_case(db=db, case=case))
            except Exception as exc:
                results.append(
                    {
                        "id": case["id"],
                        "query": case["query"],
                        "target": case["target"],
                        "attribute_filters": dict(case.get("attribute_filters") or {}),
                        "error": str(exc),
                    }
                )

    passed = [item for item in results if not item.get("error")]
    if args.json:
        print(json.dumps({"dataset": str(dataset_path), "results": results}, indent=2, ensure_ascii=False))
    else:
        print(f"Dataset: {dataset_path}")
        for item in results:
            if item.get("error"):
                print(f"- {item['id']}: ERROR {item['error']}")
                continue
            print(
                f"- {item['id']} | target={item['target']} | "
                f"current_recall={item['current_recall']:.4f} | vector_precision={item['vector_precision']:.4f}"
            )
            print(f"  current reply: {item['current_reply']}")
            if item.get("vector_error"):
                print(f"  vector  reply: unavailable ({item['vector_error']})")
            else:
                print(f"  vector  reply: {item['vector_reply']}")
            print(f"  current: {', '.join(item['current_values']) or '(none)'}")
            print(f"  vector:  {', '.join(item['vector_values']) or '(none)'}")
            print(f"  overlap: {', '.join(item['overlap']) or '(none)'}")

        if passed:
            avg_recall = sum(float(item.get("current_recall", 0.0)) for item in passed) / len(passed)
            avg_precision = sum(float(item.get("vector_precision", 0.0)) for item in passed) / len(passed)
            print(f"\nAverage current recall: {avg_recall:.4f}")
            print(f"Average vector precision: {avg_precision:.4f}")

    return 0 if len(passed) == len(results) else 1


def main() -> int:
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
