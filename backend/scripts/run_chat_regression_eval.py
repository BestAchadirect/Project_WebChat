import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.services.chat import regression_eval


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chat regression dataset evaluation.")
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(regression_eval.default_dataset_path()),
        help="Path to the regression dataset JSON file.",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset).resolve()
    cases = regression_eval.load_regression_cases(dataset_path)
    summary = regression_eval.run_regression_suite(cases)

    print(f"Dataset: {dataset_path}")
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
