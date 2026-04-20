import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.services.chat.observability import regression_eval


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chat regression dataset evaluation.")
    parser.add_argument(
        "--dataset",
        type=str,
        default="",
        help="Optional path to a regression dataset JSON file. Defaults to the built-in routing/parser datasets.",
    )
    args = parser.parse_args()

    dataset_arg = str(args.dataset or "").strip()
    dataset_path = Path(dataset_arg).resolve() if dataset_arg else None
    cases = regression_eval.load_regression_cases(dataset_path)
    summary = regression_eval.run_regression_suite(cases)

    if dataset_path is not None:
        print(f"Dataset: {dataset_path}")
    else:
        print("Datasets:")
        for path in regression_eval.default_dataset_paths():
            print(f"- {path}")
    print(
        f"Total: {summary['total']} | Passed: {summary['passed']} | Failed: {summary['failed']}"
    )
    print(f"By kind: {summary['by_kind']}")

    failures = list(summary.get("failures") or [])
    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- {failure['name']} ({failure['kind']}):")
            for mismatch in list(failure.get("mismatches") or []):
                print(f"  - {mismatch}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
