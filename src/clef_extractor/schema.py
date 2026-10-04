"""Field definitions: loading, the extractor's JSON schema, and value normalization."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from dateutil import parser as dateparser

FieldType = Literal["string", "number", "date"]
TYPES: tuple[str, ...] = ("string", "number", "date")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class SchemaError(ValueError):
    """The fields definition is invalid."""


@dataclass(frozen=True)
class Field:
    name: str
    type: FieldType
    description: str
    required: bool = False


def parse_fields(data: object) -> list[Field]:
    if not isinstance(data, dict) or not data:
        raise SchemaError("fields file must be a non-empty JSON object")
    fields = []
    for name, spec in data.items():
        if not NAME_RE.match(name):
            raise SchemaError(f"invalid field name {name!r}: use letters, digits and underscores")
        if not isinstance(spec, dict):
            raise SchemaError(f"field {name!r}: definition must be an object")
        ftype = spec.get("type", "string")
        if ftype not in TYPES:
            raise SchemaError(f"field {name!r}: type must be one of {', '.join(TYPES)}")
        description = spec.get("description")
        if not isinstance(description, str) or not description.strip():
            raise SchemaError(f"field {name!r}: description is required")
        required = spec.get("required", False)
        if not isinstance(required, bool):
            raise SchemaError(f"field {name!r}: required must be true or false")
        fields.append(Field(name, ftype, description.strip(), required))
    return fields


def load_fields(path: str | Path) -> list[Field]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SchemaError(f"cannot read fields file {path}: {e}") from e
    return parse_fields(data)


def _nullable(json_type: str, description: str) -> dict:
    return {"type": [json_type, "null"], "description": description}


def extraction_json_schema(fields: list[Field]) -> dict:
    """Strict JSON schema: every field → {raw, page, quote}, each nullable."""
    properties = {
        f.name: {
            "type": "object",
            "description": f"{f.description} (type: {f.type})",
            "additionalProperties": False,
            "required": ["raw", "page", "quote"],
            "properties": {
                "raw": _nullable("string", "The value exactly as printed in the document, or null if absent"),
                "page": _nullable("integer", "1-based page number where the value is printed"),
                "quote": _nullable("string", "Short verbatim snippet from the document containing the value"),
            },
        }
        for f in fields
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [f.name for f in fields],
        "properties": properties,
    }


_THOUSANDS = re.compile(r"^\d{1,3}([.,]\d{3})+$")
_CURRENCY = re.compile(r"[$€£¥%]|\b[A-Za-z]{3}\b")
# After removing currency marks: optional sign or parentheses, digits with grouping, optional trailing minus.
_NUMBER_SHAPE = re.compile(r"^\(?[-+]?\s*\d[\d.,'\s\u00a0\u202f]*\)?\s*-?$")


def _normalize_number(raw: str) -> float:
    text = _CURRENCY.sub("", raw).strip()
    if not _NUMBER_SHAPE.match(text):
        raise ValueError(f"not a number: {raw!r}")
    negative = text.startswith("-") or text.endswith("-") or (text.startswith("(") and text.endswith(")"))
    s = re.sub(r"[^\d.,]", "", text)
    if "," in s and "." in s:
        decimal = "," if s.rfind(",") > s.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        s = s.replace(thousands, "").replace(decimal, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        if s.count(sep) > 1:
            if not _THOUSANDS.match(s):
                raise ValueError(f"not a number: {raw!r}")
            s = s.replace(sep, "")
        else:
            head, tail = s.split(sep)
            # One separator + exactly 3 digits = thousands ("1.200", "1,200"), unless the integer part is 0.
            s = head + tail if len(tail) == 3 and head.strip("0") else f"{head or '0'}.{tail}"
    try:
        value = float(s)
    except ValueError as e:
        raise ValueError(f"not a number: {raw!r}") from e
    return -value if negative else value


_FR_MONTHS = {
    "janvier": "january", "février": "february", "fevrier": "february", "mars": "march",
    "avril": "april", "mai": "may", "juin": "june", "juillet": "july", "août": "august",
    "aout": "august", "septembre": "september", "octobre": "october", "novembre": "november",
    "décembre": "december", "decembre": "december",
}
_HAS_YEAR = re.compile(r"\d{4}|\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2}\b")
_YEAR_FIRST = re.compile(r"(?<!\d)\d{4}[-/.]?\d{1,2}[-/.]?\d{1,2}(?!\d)")


def _normalize_date(raw: str) -> str:
    s = raw.strip().lower()
    if not _HAS_YEAR.search(s):
        raise ValueError(f"not a date: {raw!r}")
    for fr, en in _FR_MONTHS.items():
        s = re.sub(rf"\b{fr}\b", en, s)
    iso = bool(_YEAR_FIRST.search(s))  # 2026-10-03, 2026/10/03, 2026.10.03, 20261003
    try:
        # Parse with two different defaults: if they disagree, a component was missing and got invented.
        a = dateparser.parse(s, dayfirst=not iso, yearfirst=iso, default=datetime(2000, 1, 1))
        b = dateparser.parse(s, dayfirst=not iso, yearfirst=iso, default=datetime(2001, 2, 2))
    except (ValueError, OverflowError) as e:
        raise ValueError(f"not a date: {raw!r}") from e
    if a.date() != b.date():
        raise ValueError(f"incomplete date: {raw!r}")
    return a.date().isoformat()


def normalize(field_type: FieldType, raw: str) -> str | float:
    """Turn a value as printed into a typed value. Raises ValueError if it doesn't fit the type."""
    if field_type == "number":
        return _normalize_number(raw)
    if field_type == "date":
        return _normalize_date(raw)
    text = raw.strip()
    if not text:
        raise ValueError("empty string")
    return text
