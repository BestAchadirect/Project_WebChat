from __future__ import annotations

import argparse
import fnmatch
import subprocess
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

# Runtime/generated artifacts that must never be tracked in git.
BANNED_GLOBS: Sequence[str] = (
    "backend/.venv/**",
    "backend/venv/**",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/*.pyc.*",
    "**/*.pyo",
    "backend/.tmp_pyc/**",
    "backend/pytest-cache-files-*/**",
    "backend/uploads/**",
    "backend/logs/**",
    "frontend-admin/node_modules/**",
    "frontend-admin/dist/**",
)

# Legacy files intentionally removed during cleanup; block accidental reintroduction.
BANNED_EXACT_PATHS: Sequence[str] = (
    "backend/agents/optimize_code.md",
    "backend/app/core/security.py",
    "backend/app/services/contracts.py",
    "backend/tests/acha_chatbot_faq_test_script.json",
    "tests/backend/conftest.py",
    "tests/backend/test_auth.py",
    "tests/frontend/chat.spec.js",
    "tests/verify_chat_setup.py",
    "tests/verify_import_service.py",
    "tests/verify_product_service_sku.py",
)


def _tracked_existing_files(repo_root: Path) -> List[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    raw = result.stdout.decode("utf-8", errors="replace")
    files: List[str] = []
    for entry in raw.split("\x00"):
        if not entry:
            continue
        rel = entry.replace("\\", "/")
        if (repo_root / rel).exists():
            files.append(rel)
    return sorted(set(files))


def _find_violations(paths: Iterable[str]) -> List[Tuple[str, str]]:
    violations: List[Tuple[str, str]] = []
    banned_exact = set(BANNED_EXACT_PATHS)

    for rel_path in paths:
        if rel_path in banned_exact:
            violations.append((rel_path, "exact"))
            continue
        for pattern in BANNED_GLOBS:
            if fnmatch.fnmatch(rel_path, pattern):
                violations.append((rel_path, f"glob:{pattern}"))
                break

    return sorted(violations, key=lambda item: item[0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when banned runtime artifacts or legacy removed files are tracked."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root path.",
    )
    parser.add_argument(
        "--dump-tracked",
        action="store_true",
        help="Print tracked existing files and exit 0.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()

    try:
        tracked = _tracked_existing_files(repo_root)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        print("Failed to read tracked files via git ls-files.")
        if stderr:
            print(stderr)
        return 2
    except FileNotFoundError:
        print("Git executable not found.")
        return 2

    if args.dump_tracked:
        for item in tracked:
            print(item)
        return 0

    violations = _find_violations(tracked)
    if violations:
        print("Repository hygiene violations detected:")
        for rel_path, reason in violations:
            print(f"  - {rel_path} ({reason})")
        return 1

    print("Repository hygiene check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

