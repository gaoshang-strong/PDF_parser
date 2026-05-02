"""JSON writer utility for pretty-printed output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_pretty_json(path: Path, data: Any) -> None:
    """Write data to path as pretty-printed JSON (2-space indent, sorted keys)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
