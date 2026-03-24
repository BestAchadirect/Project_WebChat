import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.services.chat.observability import accuracy_eval


def main() -> int:
    parser = argparse.ArgumentParser(description="Run product and FAQ chat accuracy evaluation.")
    parser.add_argument(
        "--suite",
        type=str,
        choices=("all", "product", "faq"),
        default="all",
        help="Built-in suite to run when --dataset is not provided.",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="Path to a dataset JSON file. Can be provided multiple times.",
    )
    parser.add_argument(
        "--actual-results",
        type=str,
        default="",
        help="Optional JSON file containing captured chatbot responses keyed by case id.",
    )
    args = parser.parse_args()

    dataset_paths = [Path(item).resolve() for item in list(args.dataset or [])]
    cases = accuracy_eval.load_accuracy_cases(dataset_paths, suite=args.suite)
    actual_results = (
        accuracy_eval.load_actual_results(Path(args.actual_results).resolve())
        if str(args.actual_results or "").strip()
        else None
    )
    summary = accuracy_eval.run_accuracy_suite(cases, actual_results=actual_results)

    dataset_label = ", ".join(
        [str(path) for path in dataset_paths]
        or [str(path) for path in accuracy_eval.default_dataset_paths(suite=args.suite)]
    )
    print(f"Datasets: {dataset_label}")
    print(
        f"Total: {summary['total']} | Passed: {summary['passed']} | Failed: {summary['failed']}"
    )
    print(f"By suite: {summary['by_suite']}")
    print(f"By bucket: {summary['by_bucket']}")
    print(f"By kind: {summary['by_kind']}")

    failures = list(summary.get("failures") or [])
    if failures:
        print("\nFailures:")
        for failure in failures:
            print(
                f"- {failure.get('id') or failure['name']} "
                f"({failure.get('suite')}/{failure.get('bucket')}/{failure['kind']}):"
            )
            for mismatch in list(failure.get("mismatches") or []):
                print(f"  - {mismatch}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
