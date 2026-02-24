from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Iterable, List, Set, Tuple

LEGACY_MODULES = {
    "chat_service",
    "data_import_service",
    "agent_tools",
    "agent_orchestrator",
    "llm_service",
    "answer_polisher",
    "response_renderer",
    "eav_service",
    "product_attribute_sync_service",
    "knowledge_pipeline",
    "task_service",
    "ticket_service",
    "rag_service",
    "magento_service",
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "_tmp_legacy_imports",
    "_tmp_legacy_imports_test",
    "_tmp_checker_imports",
    "_checker_imports_sandbox",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
}


def _iter_python_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    files: List[Path] = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if any(part.startswith("_tmp_legacy_imports") for part in path.parts):
            continue
        files.append(path)
    return files


def _extract_signatures(file_path: Path) -> Set[str]:
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))
    signatures: Set[str] = set()
    legacy_full = {f"app.services.{name}" for name in LEGACY_MODULES}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in legacy_full:
                imported = ", ".join(alias.name for alias in node.names)
                signatures.add(f"from {module} import {imported}")
            elif module == "app.services":
                names = [alias.name for alias in node.names if alias.name in LEGACY_MODULES]
                if names:
                    signatures.add(f"from app.services import {', '.join(names)}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in legacy_full:
                    signatures.add(f"import {alias.name}")
    return signatures


def collect_legacy_import_entries(repo_root: Path, scan_roots: Iterable[str]) -> Set[str]:
    findings: Set[str] = set()
    for root_name in scan_roots:
        root_path = repo_root / root_name
        for file_path in _iter_python_files(root_path):
            rel_path = file_path.relative_to(repo_root).as_posix()
            for signature in _extract_signatures(file_path):
                findings.add(f"{rel_path}|{signature}")
    return findings


def load_allowlist(baseline_path: Path) -> Set[str]:
    if not baseline_path.exists():
        return set()
    lines = baseline_path.read_text(encoding="utf-8").splitlines()
    allowed: Set[str] = set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        allowed.add(line)
    return allowed


def run_check(
    *,
    repo_root: Path,
    baseline_path: Path,
    scan_roots: Iterable[str],
) -> Tuple[Set[str], Set[str]]:
    findings = collect_legacy_import_entries(repo_root=repo_root, scan_roots=scan_roots)
    allowlist = load_allowlist(baseline_path)
    new_entries = findings - allowlist
    return findings, new_entries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Block new imports from deprecated service wrappers.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root path.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("backend/config/legacy_import_allowlist.txt"),
        help="Allowlist file path (relative to repo root by default).",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        default=["backend", "tests"],
        help="Root directory to scan relative to repo root. Can be repeated.",
    )
    parser.add_argument(
        "--dump-current",
        action="store_true",
        help="Print current findings and exit 0.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    baseline_path = args.baseline
    if not baseline_path.is_absolute():
        baseline_path = (repo_root / baseline_path).resolve()

    findings, new_entries = run_check(
        repo_root=repo_root,
        baseline_path=baseline_path,
        scan_roots=args.scan_root,
    )

    if args.dump_current:
        for entry in sorted(findings):
            print(entry)
        return 0

    if new_entries:
        print("Found new legacy wrapper imports not in allowlist:")
        for entry in sorted(new_entries):
            print(f"  - {entry}")
        print(f"\nUpdate allowlist only when usage is intentionally compatibility-only: {baseline_path}")
        return 1

    print("No new legacy wrapper imports detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
