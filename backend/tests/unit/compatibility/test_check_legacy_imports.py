from __future__ import annotations

from pathlib import Path

from scripts.check_legacy_imports import collect_legacy_import_entries


def test_legacy_import_checker_flags_removed_chat_runtime_imports(tmp_path: Path) -> None:
    repo = tmp_path
    package = repo / "backend" / "sample"
    package.mkdir(parents=True)
    (package / "old_runtime_imports.py").write_text(
        "\n".join(
            [
                "import app.services.chat.runtime.unified_chat_runtime",
                "from app.services.chat.runtime import execution_coordinator",
                "from app.services.chat.runtime.unified_chat_runtime import process_chat",
            ]
        ),
        encoding="utf-8",
    )

    findings = collect_legacy_import_entries(repo_root=repo, scan_roots=["backend"])

    assert findings == {
        "backend/sample/old_runtime_imports.py|import app.services.chat.runtime.unified_chat_runtime",
        "backend/sample/old_runtime_imports.py|from app.services.chat.runtime import execution_coordinator",
        "backend/sample/old_runtime_imports.py|from app.services.chat.runtime.unified_chat_runtime import process_chat",
    }
