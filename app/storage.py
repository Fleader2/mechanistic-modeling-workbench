"""Local filesystem storage for the Workbench's own durable file artifacts (currently just a
saved time-series dataset's own original workbook). One valid implementation of the existing
``artifact_reference``-as-opaque-string contract (``app.models.dataset_reference
.DatasetReference.artifact_reference`` et al.) -- see ``app.config.settings.Settings
.artifacts_dir``'s own docstring.

Content-addressed by design: the path a blob is written to is a pure function of its own
sha256, so saving byte-identical content twice writes to the identical path -- the one piece
of the Downloadable Two-Tab Excel Template increment's own duplicate-save protection that lives
here rather than in a database uniqueness constraint (``app.persistence.time_series_dataset``
relies on this to make ``persist_dataset_reference``'s own existing ``(project_id, name,
artifact_reference)`` dedup key actually catch a re-saved, identical workbook).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.config.settings import get_settings


def _artifacts_root() -> Path:
    return Path(get_settings().artifacts_dir)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_dataset_workbook(data: bytes) -> tuple[str, str]:
    """Write ``data`` to ``<artifacts_dir>/datasets/<sha256>.xlsx`` (a no-op if that exact
    content is already on file) and return ``(artifact_reference, checksum)``. Always safe to
    call more than once with identical bytes."""
    checksum = sha256_hex(data)
    directory = _artifacts_root() / "datasets"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{checksum}.xlsx"
    if not path.is_file():
        path.write_bytes(data)
    return str(path), checksum


def read_artifact(artifact_reference: str) -> bytes:
    """Read back a previously-saved artifact by its own ``artifact_reference`` path."""
    return Path(artifact_reference).read_bytes()


__all__ = ["read_artifact", "save_dataset_workbook", "sha256_hex"]
