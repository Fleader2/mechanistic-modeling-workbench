"""Time-series experimental dataset workbook contract: template generation
(``app.time_series.template``) and parsing/validation (``app.time_series.parser``), for the
Downloadable Two-Tab Excel Template increment. See ``docs/25_time_series_dataset_import_
increment.md``.

Deliberately upstream of (and independent from) any model, Antimony species name, or alias
mapping -- task instructions: "uploading and saving a dataset must not require a model or
matching Antimony species names... model-specific alias mapping is a later increment." A
measurement column's original header text is the only identity this package ever assigns it.
"""

from __future__ import annotations

__all__: list[str] = []
