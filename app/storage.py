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


def save_blob(data: bytes, *, subdir: str, suffix: str) -> tuple[str, str]:
    """Write ``data`` to ``<artifacts_dir>/<subdir>/<sha256><suffix>`` (a no-op if that exact
    content is already on file) and return ``(artifact_reference, checksum)``. Always safe to
    call more than once with identical bytes -- the one, shared content-addressing primitive
    every durable-file-artifact increment in this repository builds on."""
    checksum = sha256_hex(data)
    directory = _artifacts_root() / subdir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{checksum}{suffix}"
    if not path.is_file():
        path.write_bytes(data)
    return str(path), checksum


def save_dataset_workbook(data: bytes) -> tuple[str, str]:
    """Write ``data`` to ``<artifacts_dir>/datasets/<sha256>.xlsx``. See ``save_blob``."""
    return save_blob(data, subdir="datasets", suffix=".xlsx")


def save_model_antimony_text(antimony_text: str) -> tuple[str, str]:
    """Write ``antimony_text`` to ``<artifacts_dir>/models/<sha256>.antimony`` (utf-8) -- the
    Model-Species Catalog Prerequisite increment's own durable retention of the authoritative
    source artifact a captured catalog was verified against, per ``app.storage``'s own existing
    convention (Downloadable Two-Tab Excel Template increment) rather than relying on the
    harness's own transient, gitignored run-output directory. See ``save_blob``."""
    return save_blob(antimony_text.encode("utf-8"), subdir="models", suffix=".antimony")


def read_artifact(artifact_reference: str) -> bytes:
    """Read back a previously-saved artifact by its own ``artifact_reference`` path."""
    return Path(artifact_reference).read_bytes()


__all__ = [
    "read_artifact",
    "save_blob",
    "save_dataset_workbook",
    "save_model_antimony_text",
    "sha256_hex",
]
