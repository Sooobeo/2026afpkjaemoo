"""Stable serialization and file output; no network or external dependencies."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


def clean(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("유한하지 않은 금액은 저장할 수 없습니다.")
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def canonical(value):
    return json.dumps(clean(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def code_digest():
    hasher = hashlib.sha256()
    for file in sorted(Path(__file__).parent.glob("*.py")):
        hasher.update(file.name.encode("utf-8"))
        hasher.update(file.read_bytes())
    return hasher.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, rows, fields=None):
    rows = [clean(r) for r in rows]
    if fields is None:
        fields = list(dict.fromkeys(k for row in rows for k in row))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or ["status"])
        writer.writeheader()
        for row in rows:
            # Nested values stay readable without Python repr literals.
            writer.writerow({k: canonical(v) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})
