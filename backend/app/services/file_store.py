"""Encrypted local file store (spec §5.1, §10.2): data/files/{claim_id}/{original|pages|reports}/..."""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.core.security import decrypt_bytes, encrypt_bytes


def _root() -> Path:
    root = settings.file_store
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe(rel: str) -> Path:
    path = (_root() / rel).resolve()
    if not str(path).startswith(str(_root().resolve())):
        raise ValueError("path traversal blocked")
    return path


def put(rel_path: str, data: bytes) -> str:
    path = _safe(rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(encrypt_bytes(data))
    tmp.replace(path)
    return rel_path


def get(rel_path: str) -> bytes:
    return decrypt_bytes(_safe(rel_path).read_bytes())


def exists(rel_path: str) -> bool:
    return _safe(rel_path).exists()


def original_path(claim_id: str, document_id: str) -> str:
    return f"{claim_id}/original/{document_id}.bin"


def page_image_path(claim_id: str, document_id: str, page_number: int) -> str:
    return f"{claim_id}/pages/{document_id}/{page_number:05d}.png.bin"


def report_path(claim_id: str, report_id: str, fmt: str) -> str:
    return f"{claim_id}/reports/{report_id}.{fmt}.bin"


def healthy() -> bool:
    try:
        probe = _root() / ".probe"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False
