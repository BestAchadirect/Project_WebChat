import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.services.chat.observability import accuracy_eval
from app.services.chat.observability.capture_eval import (
    capture_case_outputs,
    filter_capture_cases,
    write_capture_results,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture real chat responses for accuracy evaluation cases."
    )
    parser.add_argument(
        "--suite",
        type=str,
        choices=("all", "response"),
        default="response",
        help="Built-in suite to capture when --dataset is not provided.",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="Path to a dataset JSON file. Can be provided multiple times.",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path to write captured response JSON.",
    )
    parser.add_argument(
        "--channel",
        type=str,
        default="widget",
        help="Chat channel to pass into ChatService.process_chat().",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of captureable cases to run.",
    )
    args = parser.parse_args()

    dataset_paths = [Path(item).resolve() for item in list(args.dataset or [])]
    cases = accuracy_eval.load_accuracy_cases(dataset_paths, suite=args.suite)
    capture_cases = filter_capture_cases(cases)
    if int(args.limit or 0) > 0:
        capture_cases = capture_cases[: int(args.limit)]
    if not capture_cases:
        print("No captureable cases found.")
        return 1

    outputs = asyncio.run(capture_case_outputs(capture_cases, channel=str(args.channel or "widget")))
    output_path = Path(args.output).resolve()
    write_capture_results(output_path, outputs)
    print(f"Captured {len(outputs)} case(s) to {output_path}")
    return 0


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(main())
