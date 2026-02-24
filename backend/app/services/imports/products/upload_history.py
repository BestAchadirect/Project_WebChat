from __future__ import annotations

from pathlib import Path
from uuid import UUID


def product_upload_storage_path(upload_root: str | Path, upload_id: UUID, filename: str) -> Path:
    root = Path(upload_root)
    safe_name = Path(filename).name
    return root / "product_uploads" / str(upload_id) / safe_name


def ensure_upload_path_in_root(upload_root: str | Path, file_path: str | Path) -> Path:
    root = Path(upload_root).resolve()
    candidate = Path(file_path)
    resolved = candidate.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("Invalid file path outside upload root")
    return resolved
