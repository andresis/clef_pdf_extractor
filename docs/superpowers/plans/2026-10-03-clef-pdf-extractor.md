# clef-pdf-extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CLI that extracts per-request fields from any PDF with OpenAI GPT-6.1 Sol, validates every value against the rendered page with local clef-flash:9b, and asks the user about any required field that fails.

**Architecture:** `schema` (field defs + normalization) → `extractors/openai` (Responses API, PDF `input_file`, strict JSON schema) → `pdf` (pymupdf: locate the quoted evidence, render crop + page) → `validator` (clef-flash `noul` questions, score = min) → `gate` + `review_cli` (strict gate, interactive prompt) → `cli` (JSON output, exit codes). Every external service sits behind a small client object so units are tested with fakes; live services are behind pytest markers.

**Tech Stack:** Python ≥3.11, uv, pymupdf, httpx, openai (Responses API), python-dateutil, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-clef-pdf-extractor-design.md`

**Plan refinements vs. spec (deliberate, small):**
- `Candidate` carries `raw/page/quote` only; normalization to `value` and the type check happen in the validator (one place), and `FieldResult` holds the `value`.
- One clef-flash request per field (the spec's optional batching is skipped — YAGNI).
- The console command is `clef-extract` (avoids clashing with generic `extract` binaries); `uv run clef-extract …`.

## Global Constraints

- Python ≥ 3.11, uv-managed, `src/` layout, package `clef_extractor`.
- Validator: model `clef-flash:9b` at `http://localhost:11434`, endpoint `POST /v1/systemone`, `noul` questions only.
- Extractor: OpenAI Responses API, default model `gpt-6.1-sol` (override `--model` / `OPENAI_MODEL`), `reasoning: {"effort": "low"}`, strict `json_schema` via `text.format`, auth `OPENAI_API_KEY`.
- Field types: `string`, `number`, `date` only (scalars). Field names match `^[A-Za-z_][A-Za-z0-9_]{0,63}$`.
- Score = `min(shown, semantic)`; pass iff `score >= threshold`; default threshold `0.5`.
- Images: located → crop (full page width, ±150pt, 150 dpi) + full page at 100 dpi; not located → full page at 100 dpi.
- PDF limit 50 MB; encrypted / unreadable PDFs rejected up front.
- Page numbers are 1-based everywhere.
- clef health check runs before any OpenAI request.
- Exit codes: 0 complete, 2 a required field skipped, 1 error.
- Default `pytest` run makes no network calls; live tests use markers `clef` and `e2e`.

## Review Focus

1. **Non-interactive run** (stdin piped/closed, e.g. CI): the review prompt hits EOF → treat as skip, still print valid JSON, exit 2. → Task 6 `test_eof_skips`, Task 7 `test_required_failure_without_input_exits_2`.
2. **Extractor reports a wrong or impossible page** (0, 99, null): validator relocates by text, or scores 0 without calling clef and without crashing. → Task 5 `test_located_value_corrects_page`, `test_unlocatable_with_invalid_page_scores_zero`.
3. **Quote paraphrased or whitespace differs** from the PDF text: locate with normalized whitespace, then fall back to searching the raw value. → Task 2 `test_locate_normalizes_whitespace`, Task 5 `test_falls_back_to_raw_when_quote_paraphrased`.
4. **Ambiguous numbers/dates**: `1.200`/`1,200` → 1200, `0.125` → 0.125, `03/10/2026` → 2026-10-03 (day-first), `10/25/2026` → month-first fallback. → Task 1 parametrized normalization tests.
5. **Person types an invalid correction or presses Enter on a missing / ill-typed value**: re-prompt, never store an invalid value. → Task 6 `test_invalid_correction_reprompts`, `test_cannot_accept_missing_value`, `test_cannot_accept_type_invalid_value`.

---

## File Structure

```
pyproject.toml                         # Task 1
tasks/todo.md                          # Task 1 (progress tracker, per user's global instructions)
src/clef_extractor/__init__.py         # Task 1
src/clef_extractor/schema.py           # Task 1 — Field, parse/load, JSON schema, normalize
src/clef_extractor/_pdfgen.py          # Task 2 — synthetic PDF builder (tests + eval)
src/clef_extractor/pdf.py              # Task 2 — Document, Location, PdfError
src/clef_extractor/clef.py             # Task 3 — ClefClient, ClefError
src/clef_extractor/extractors/__init__.py  # Task 4
src/clef_extractor/extractors/base.py      # Task 4 — Candidate, Extractor, ExtractionError
src/clef_extractor/extractors/openai.py    # Task 4 — OpenAIExtractor
src/clef_extractor/validator.py        # Task 5 — FieldResult, Validator
src/clef_extractor/gate.py             # Task 6 — Decision, apply_gate
src/clef_extractor/review_cli.py       # Task 6 — CliReviewer
src/clef_extractor/cli.py              # Task 7 — run(), main()
README.md                              # Task 7
src/clef_extractor/calibration.py      # Task 8 — Trial, summarize, recommend
eval/make_samples.py                   # Task 8
eval/calibrate.py                      # Task 8
tests/test_schema.py  tests/test_pdf.py  tests/test_clef.py  tests/test_openai_extractor.py
tests/test_validator.py  tests/test_validator_live.py  tests/test_gate.py  tests/test_review_cli.py
tests/test_cli.py  tests/test_calibration.py  tests/test_e2e.py
```

---

### Task 1: Project scaffold + field schema

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `tasks/todo.md`, `src/clef_extractor/__init__.py`, `src/clef_extractor/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FieldType = Literal["string", "number", "date"]`
  - `@dataclass(frozen=True) class Field: name: str; type: FieldType; description: str; required: bool = False`
  - `class SchemaError(ValueError)`
  - `parse_fields(data: object) -> list[Field]` (raises `SchemaError`)
  - `load_fields(path: str | Path) -> list[Field]` (raises `SchemaError`)
  - `extraction_json_schema(fields: list[Field]) -> dict`
  - `normalize(field_type: FieldType, raw: str) -> str | float` (raises `ValueError`; number → `float`, date → ISO `str`, string → stripped `str`)

- [ ] **Step 1: Create the scaffold**

`pyproject.toml`:
```toml
[project]
name = "clef-extractor"
version = "0.1.0"
description = "Extract PDF fields with OpenAI GPT-Sol, validated locally by clef-flash"
requires-python = ">=3.11"
dependencies = [
    "pymupdf>=1.24",
    "httpx>=0.27",
    "openai>=1.66",
    "python-dateutil>=2.9",
]

[project.scripts]
clef-extract = "clef_extractor.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/clef_extractor"]

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "clef: needs local Ollama with clef-flash:9b",
    "e2e: needs OPENAI_API_KEY and Ollama; costs money",
]
addopts = "-m 'not clef and not e2e'"
```

`.gitignore`:
```
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
eval/samples/
eval/results.csv
```

`src/clef_extractor/__init__.py`:
```python
"""Extract PDF fields with a cloud LLM and validate them locally with clef-flash."""
```

`tasks/todo.md`:
```markdown
# clef-pdf-extractor — progress

Plan: docs/superpowers/plans/2026-10-03-clef-pdf-extractor.md

- [ ] Task 1: Project scaffold + field schema
- [ ] Task 2: PDF document (locate, render)
- [ ] Task 3: clef-flash client
- [ ] Task 4: OpenAI extractor (spike first)
- [ ] Task 5: Validator
- [ ] Task 6: Gate + review CLI
- [ ] Task 7: CLI wiring + README
- [ ] Task 8: Calibration set + script

## Review
```

Run: `uv sync`
Expected: creates `.venv`, installs deps, no errors.

- [ ] **Step 2: Write the failing tests**

`tests/test_schema.py`:
```python
import json

import pytest

from clef_extractor.schema import (
    Field,
    SchemaError,
    extraction_json_schema,
    load_fields,
    normalize,
    parse_fields,
)


def test_parse_fields_defaults_and_order():
    fields = parse_fields({
        "total": {"type": "number", "description": "Grand total", "required": True},
        "note": {"description": "Free text"},
    })
    assert fields == [
        Field("total", "number", "Grand total", True),
        Field("note", "string", "Free text", False),
    ]


@pytest.mark.parametrize("data, msg", [
    ({}, "non-empty"),
    ([], "non-empty"),
    ({"bad name": {"description": "x"}}, "invalid field name"),
    ({"x": {"type": "money", "description": "x"}}, "type must be"),
    ({"x": {"type": "string"}}, "description is required"),
    ({"x": {"description": "x", "required": "yes"}}, "required must be"),
    ({"x": "string"}, "must be an object"),
])
def test_parse_fields_rejects_invalid(data, msg):
    with pytest.raises(SchemaError, match=msg):
        parse_fields(data)


def test_load_fields_reads_file(tmp_path):
    p = tmp_path / "fields.json"
    p.write_text(json.dumps({"d": {"type": "date", "description": "Date"}}))
    assert load_fields(p) == [Field("d", "date", "Date", False)]


def test_load_fields_bad_json(tmp_path):
    p = tmp_path / "fields.json"
    p.write_text("{nope")
    with pytest.raises(SchemaError, match="cannot read"):
        load_fields(p)


def test_extraction_schema_is_strict():
    s = extraction_json_schema([Field("total", "number", "Grand total", True)])
    assert s["type"] == "object"
    assert s["additionalProperties"] is False
    assert s["required"] == ["total"]
    t = s["properties"]["total"]
    assert t["additionalProperties"] is False
    assert t["required"] == ["raw", "page", "quote"]
    assert t["properties"]["raw"]["type"] == ["string", "null"]
    assert t["properties"]["page"]["type"] == ["integer", "null"]
    assert t["properties"]["quote"]["type"] == ["string", "null"]
    assert "Grand total" in t["description"]


@pytest.mark.parametrize("raw, expected", [
    ("1.200,00 EUR", 1200.0),
    ("$2,652.13", 2652.13),
    ("1 200,50 €", 1200.5),
    ("1 200,50", 1200.5),
    ("12.45", 12.45),
    ("1,5", 1.5),
    ("1.200", 1200.0),
    ("1,200", 1200.0),
    ("0.125", 0.125),
    ("1.234.567,89", 1234567.89),
    ("1,234,567", 1234567.0),
    ("-42,10", -42.10),
    ("(15.00)", -15.0),
    ("200", 200.0),
])
def test_normalize_number(raw, expected):
    assert normalize("number", raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["abc", "", "1.2.3", "EUR"])
def test_normalize_number_rejects(raw):
    with pytest.raises(ValueError):
        normalize("number", raw)


@pytest.mark.parametrize("raw, expected", [
    ("03/10/2026", "2026-10-03"),
    ("2026-10-03", "2026-10-03"),
    ("03.10.2026", "2026-10-03"),
    ("10/25/2026", "2026-10-25"),
    ("October 3, 2026", "2026-10-03"),
    ("3 octobre 2026", "2026-10-03"),
    ("14 février 1990", "1990-02-14"),
    ("03/10/26", "2026-10-03"),
    ("2026-09-28 08:14", "2026-09-28"),
])
def test_normalize_date(raw, expected):
    assert normalize("date", raw) == expected


@pytest.mark.parametrize("raw", ["", "soon", "5", "13"])
def test_normalize_date_rejects(raw):
    with pytest.raises(ValueError):
        normalize("date", raw)


def test_normalize_string():
    assert normalize("string", "  ACME SARL ") == "ACME SARL"
    with pytest.raises(ValueError):
        normalize("string", "   ")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clef_extractor.schema'`

- [ ] **Step 4: Implement `schema.py`**

`src/clef_extractor/schema.py`:
```python
"""Field definitions: loading, the extractor's JSON schema, and value normalization."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
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


def _normalize_number(raw: str) -> float:
    text = raw.strip()
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    s = re.sub(r"[^\d.,]", "", text)
    if not re.search(r"\d", s):
        raise ValueError(f"not a number: {raw!r}")
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
_ISO_START = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}\b")


def _normalize_date(raw: str) -> str:
    s = raw.strip().lower()
    if not _HAS_YEAR.search(s):
        raise ValueError(f"not a date: {raw!r}")
    for fr, en in _FR_MONTHS.items():
        s = re.sub(rf"\b{fr}\b", en, s)
    iso = bool(_ISO_START.match(s))
    try:
        parsed = dateparser.parse(s, dayfirst=not iso, yearfirst=iso)
    except (ValueError, OverflowError) as e:
        raise ValueError(f"not a date: {raw!r}") from e
    return parsed.date().isoformat()


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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema.py -q`
Expected: all PASS. If a dateutil case fails (e.g. `10/25/2026`), fix `_normalize_date`, not the test — these are the Review Focus #4 cases.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore tasks/todo.md src tests
git commit -m "feat: project scaffold and field schema with normalization"
```
Mark Task 1 done in `tasks/todo.md` (commit with the next task).

---

### Task 2: PDF document — locate evidence and render images

**Files:**
- Create: `src/clef_extractor/_pdfgen.py`, `src/clef_extractor/pdf.py`
- Test: `tests/test_pdf.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `_pdfgen.build_pdf(pages: list[list[tuple]], image_only: bool = False, dpi: int = 150) -> bytes` — each line is `(text, fontsize)` or `(text, fontsize, x)`; lines stack from y=60.
  - `class PdfError(Exception)`; `MAX_BYTES = 50 * 1024 * 1024`
  - `@dataclass(frozen=True) class Location: page: int; bbox: tuple[float, float, float, float]`
  - `class Document(data: bytes, name: str = "document.pdf")` with `.data: bytes`, `.name: str`, `Document.from_path(path) -> Document`, `.page_count: int`, `.valid_page(page) -> bool`, `.has_text(page: int) -> bool`, `.locate(needle: str | None, hint_page: int | None = None) -> Location | None`, `.render_page(page: int, dpi: int = 100) -> bytes` (PNG), `.render_crop(page: int, bbox, dpi: int = 150, margin: float = 150.0) -> bytes` (PNG)

- [ ] **Step 1: Write the PDF builder (test helper, used by tests and eval)**

`src/clef_extractor/_pdfgen.py`:
```python
"""Build simple synthetic PDFs for tests and the calibration set."""

from __future__ import annotations

import pymupdf


def build_pdf(pages: list[list[tuple]], image_only: bool = False, dpi: int = 150) -> bytes:
    """Each page is a list of lines: (text, fontsize) or (text, fontsize, x).

    image_only=True rasterizes every page, producing a PDF with no text layer (a "scan").
    """
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 60.0
        for line in lines:
            text, size = line[0], line[1]
            x = line[2] if len(line) > 2 else 50.0
            if text:
                page.insert_text((x, y), text, fontsize=size)
            y += size * 1.6
    if image_only:
        scanned = pymupdf.open()
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            new_page = scanned.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, pixmap=pix)
        doc = scanned
    return doc.tobytes()
```

- [ ] **Step 2: Write the failing tests**

`tests/test_pdf.py`:
```python
import pymupdf
import pytest

from clef_extractor import pdf
from clef_extractor._pdfgen import build_pdf
from clef_extractor.pdf import Document, PdfError

INVOICE = [[
    ("FACTURE N° 2026-1042", 16),
    ("Date: 03/10/2026", 11),
    ("Sous-total HT: 1.000,00 EUR", 11, 300),
    ("Total TTC: 1.200,00 EUR", 11, 300),
]]
TWO_PAGES = [[("Page one header", 11)], [("Total TTC: 1.200,00 EUR", 11, 300)]]


def test_rejects_non_pdf():
    with pytest.raises(PdfError, match="not a readable PDF|has no pages"):  # pymupdf may "repair" to 0 pages
        Document(b"hello world", "x.pdf")


def test_rejects_encrypted():
    doc = pymupdf.open(stream=build_pdf(INVOICE), filetype="pdf")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with pytest.raises(PdfError, match="encrypted"):
        Document(data)


def test_rejects_oversized(monkeypatch):
    monkeypatch.setattr(pdf, "MAX_BYTES", 10)
    with pytest.raises(PdfError, match="limit"):
        Document(build_pdf(INVOICE))


def test_from_path_missing_file(tmp_path):
    with pytest.raises(PdfError, match="cannot read"):
        Document.from_path(tmp_path / "nope.pdf")


def test_page_count_and_valid_page():
    doc = Document(build_pdf(TWO_PAGES))
    assert doc.page_count == 2
    assert doc.valid_page(1) and doc.valid_page(2)
    assert not doc.valid_page(0) and not doc.valid_page(3) and not doc.valid_page(None)


def test_locate_finds_page_and_bbox_on_second_page():
    loc = Document(build_pdf(TWO_PAGES)).locate("Total TTC: 1.200,00 EUR", hint_page=1)
    assert loc.page == 2
    x0, y0, x1, y1 = loc.bbox
    assert x0 >= 290 and x1 > x0 and y1 > y0


def test_locate_normalizes_whitespace():
    loc = Document(build_pdf(INVOICE)).locate("Total  TTC:\n1.200,00 EUR")
    assert loc is not None and loc.page == 1


def test_locate_prefers_hint_page():
    data = build_pdf([[("Total: 5,00", 11)], [("Total: 5,00", 11)]])
    assert Document(data).locate("Total: 5,00", hint_page=2).page == 2


def test_locate_ignores_invalid_hint():
    doc = Document(build_pdf(TWO_PAGES))
    assert doc.locate("Total TTC", hint_page=0).page == 2
    assert doc.locate("Total TTC", hint_page=99).page == 2


def test_locate_returns_none_for_missing_or_empty():
    doc = Document(build_pdf(INVOICE))
    assert doc.locate("9.999,99 EUR") is None
    assert doc.locate("") is None
    assert doc.locate(None) is None


def test_has_text_false_for_image_only():
    assert Document(build_pdf(INVOICE)).has_text(1)
    assert not Document(build_pdf(INVOICE, image_only=True)).has_text(1)


def test_render_page_and_crop_are_png_and_crop_is_smaller():
    doc = Document(build_pdf(INVOICE))
    page_png = doc.render_page(1)
    loc = doc.locate("Total TTC")
    crop_png = doc.render_crop(1, loc.bbox)
    assert page_png.startswith(b"\x89PNG") and crop_png.startswith(b"\x89PNG")
    page_pix, crop_pix = pymupdf.Pixmap(page_png), pymupdf.Pixmap(crop_png)
    assert crop_pix.height < page_pix.height * 1.5  # crop at 150dpi, page at 100dpi
    page_150 = pymupdf.Pixmap(doc.render_page(1, dpi=150))
    assert abs(crop_pix.width - page_150.width) <= 1 and crop_pix.height < page_150.height


def test_page_out_of_range_raises():
    with pytest.raises(PdfError, match="out of range"):
        Document(build_pdf(INVOICE)).render_page(5)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_pdf.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clef_extractor.pdf'`

- [ ] **Step 4: Implement `pdf.py`**

`src/clef_extractor/pdf.py`:
```python
"""PDF access: validation, locating evidence text, rendering pages and crops to PNG."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

MAX_BYTES = 50 * 1024 * 1024
CROP_MARGIN = 150.0


class PdfError(Exception):
    """The PDF can't be used."""


@dataclass(frozen=True)
class Location:
    page: int  # 1-based
    bbox: tuple[float, float, float, float]


class Document:
    def __init__(self, data: bytes, name: str = "document.pdf"):
        if len(data) > MAX_BYTES:
            raise PdfError(f"{name} is {len(data) / 1e6:.1f} MB; the limit is {MAX_BYTES // (1024 * 1024)} MB")
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as e:  # pymupdf raises several types for corrupt input
            raise PdfError(f"{name} is not a readable PDF: {e}") from e
        if doc.needs_pass:
            raise PdfError(f"{name} is encrypted")
        if doc.page_count == 0:
            raise PdfError(f"{name} has no pages")
        self.data = data
        self.name = name
        self._doc = doc

    @classmethod
    def from_path(cls, path: str | Path) -> "Document":
        p = Path(path)
        try:
            data = p.read_bytes()
        except OSError as e:
            raise PdfError(f"cannot read {p}: {e}") from e
        return cls(data, p.name)

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def valid_page(self, page: object) -> bool:
        return isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= self.page_count

    def has_text(self, page: int) -> bool:
        return bool(self._page(page).get_text().strip())

    def locate(self, needle: str | None, hint_page: int | None = None) -> Location | None:
        """Find needle (whitespace-normalized) on the hint page first, then every other page."""
        needle = " ".join((needle or "").split())
        if not needle:
            return None
        order = list(range(1, self.page_count + 1))
        if self.valid_page(hint_page):
            order.remove(hint_page)
            order.insert(0, hint_page)
        for page in order:
            hits = self._page(page).search_for(needle)
            if hits:
                r = hits[0]
                return Location(page, (r.x0, r.y0, r.x1, r.y1))
        return None

    def render_page(self, page: int, dpi: int = 100) -> bytes:
        return self._page(page).get_pixmap(dpi=dpi).tobytes("png")

    def render_crop(self, page: int, bbox: tuple[float, float, float, float],
                    dpi: int = 150, margin: float = CROP_MARGIN) -> bytes:
        """Full page width, bbox ± margin points vertically."""
        pg = self._page(page)
        r = pg.rect
        clip = pymupdf.Rect(r.x0, max(r.y0, bbox[1] - margin), r.x1, min(r.y1, bbox[3] + margin))
        return pg.get_pixmap(dpi=dpi, clip=clip).tobytes("png")

    def _page(self, page: int):
        if not self.valid_page(page):
            raise PdfError(f"page {page} out of range 1..{self.page_count}")
        return self._doc[page - 1]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_pdf.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/clef_extractor/_pdfgen.py src/clef_extractor/pdf.py tests/test_pdf.py tasks/todo.md
git commit -m "feat: PDF document with evidence location and page/crop rendering"
```

---

### Task 3: clef-flash client

**Files:**
- Create: `src/clef_extractor/clef.py`
- Test: `tests/test_clef.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ClefError(Exception)`
  - `class ClefClient(base_url: str = "http://localhost:11434", model: str = "clef-flash:9b", timeout: float = 120.0, transport: httpx.BaseTransport | None = None)` with `.model: str`, `.health() -> None` (raises `ClefError`), `.ask(state: str, questions: dict[str, str], images: Sequence[bytes] = ()) -> dict[str, float]` (raises `ClefError`). `questions` maps question key → instruction text; returns key → `noul` probability.

- [ ] **Step 1: Write the failing tests**

`tests/test_clef.py`:
```python
import base64
import json

import httpx
import pytest

from clef_extractor.clef import ClefClient, ClefError


def client(handler):
    return ClefClient(transport=httpx.MockTransport(handler))


def answers(**probs):
    return {"answers": {k: {"type": "noul", "noul": v} for k, v in probs.items()}}


def test_ask_sends_noul_questions_and_images():
    seen = {}

    def handler(request):
        assert request.url.path == "/v1/systemone"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=answers(shown=0.9, semantic=0.8))

    scores = client(handler).ask("the state", {"shown": "Q1", "semantic": "Q2"}, [b"png-bytes"])
    assert scores == {"shown": 0.9, "semantic": 0.8}
    assert seen["model"] == "clef-flash:9b"
    assert seen["state"] == "the state"
    assert seen["questions"]["shown"] == {"type": "noul", "instructions": "Q1"}
    assert seen["images"] == [base64.b64encode(b"png-bytes").decode()]


def test_ask_omits_images_when_none():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=answers(q=0.5))

    client(handler).ask("s", {"q": "Q"})
    assert "images" not in seen


def test_ask_raises_on_error_payload():
    handler = lambda request: httpx.Response(400, json={"error": "criteria must contain 2–26 candidates"})
    with pytest.raises(ClefError, match="criteria must contain"):
        client(handler).ask("s", {"q": "Q"})


def test_ask_raises_on_missing_answer():
    handler = lambda request: httpx.Response(200, json={"answers": {}})
    with pytest.raises(ClefError, match="unexpected"):
        client(handler).ask("s", {"q": "Q"})


def test_ask_raises_when_unreachable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ClefError, match="request failed"):
        client(handler).ask("s", {"q": "Q"})


def test_health_ok():
    handler = lambda request: httpx.Response(200, json={"models": [{"name": "clef-flash:9b"}]})
    client(handler).health()


def test_health_model_missing():
    handler = lambda request: httpx.Response(200, json={"models": [{"name": "other:1b"}]})
    with pytest.raises(ClefError, match="ollama pull clef-flash:9b"):
        client(handler).health()


def test_health_unreachable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ClefError, match="not reachable"):
        client(handler).health()


@pytest.mark.clef
def test_live_smoke():
    c = ClefClient()
    try:
        c.health()
    except ClefError as e:
        pytest.skip(str(e))
    scores = c.ask(
        "Invoice #1042. Subtotal: $100.00. Tax: $21.00. Total: $121.00",
        {"right": "Is the total 121.00?", "wrong": "Is the total 112.00?"},
    )
    assert scores["right"] > 0.8 and scores["wrong"] < 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clef.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clef_extractor.clef'`

- [ ] **Step 3: Implement `clef.py`**

`src/clef_extractor/clef.py`:
```python
"""Thin client for clef-flash's /v1/systemone endpoint on a local Ollama."""

from __future__ import annotations

import base64
from collections.abc import Sequence

import httpx


class ClefError(Exception):
    """clef-flash is unavailable or returned something unusable."""


class ClefClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "clef-flash:9b",
                 timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        self.model = model
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def health(self) -> None:
        try:
            r = self._http.get("/api/tags")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ClefError(f"Ollama not reachable at {self._http.base_url}: {e}") from e
        names = {m.get("name") for m in r.json().get("models", [])}
        if self.model not in names:
            raise ClefError(f"model {self.model} is not installed; run: ollama pull {self.model}")

    def ask(self, state: str, questions: dict[str, str], images: Sequence[bytes] = ()) -> dict[str, float]:
        """Ask boolean (noul) questions; returns question key → probability of 'yes'."""
        body: dict = {
            "model": self.model,
            "state": state,
            "questions": {k: {"type": "noul", "instructions": v} for k, v in questions.items()},
        }
        if images:
            body["images"] = [base64.b64encode(img).decode() for img in images]
        try:
            r = self._http.post("/v1/systemone", json=body)
        except httpx.HTTPError as e:
            raise ClefError(f"clef-flash request failed: {e}") from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code != 200:
            raise ClefError(f"clef-flash error ({r.status_code}): {data.get('error', r.text)}")
        try:
            return {k: float(data["answers"][k]["noul"]) for k in questions}
        except (KeyError, TypeError, ValueError) as e:
            raise ClefError(f"unexpected clef-flash response: {data}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clef.py -q` → all PASS (live test deselected).
Run: `uv run pytest tests/test_clef.py -m clef -q` → `test_live_smoke` PASS with Ollama running.

- [ ] **Step 5: Commit**

```bash
git add src/clef_extractor/clef.py tests/test_clef.py tasks/todo.md
git commit -m "feat: clef-flash client with health check"
```

---

### Task 4: OpenAI extractor (spike first)

**Files:**
- Create: `src/clef_extractor/extractors/__init__.py`, `src/clef_extractor/extractors/base.py`, `src/clef_extractor/extractors/openai.py`
- Throwaway (not committed): `scripts/spike_openai.py`
- Test: `tests/test_openai_extractor.py`

**Interfaces:**
- Consumes: `Field`, `extraction_json_schema` (Task 1); `build_pdf` (Task 2, spike only).
- Produces:
  - `@dataclass(frozen=True) class Candidate: name: str; raw: str | None; page: int | None; quote: str | None`
  - `class ExtractionError(Exception)`
  - `class Extractor(Protocol): name: str; def extract(self, pdf: bytes, filename: str, fields: list[Field]) -> dict[str, Candidate]`
  - `DEFAULT_MODEL = "gpt-6.1-sol"`
  - `class OpenAIExtractor(model: str = DEFAULT_MODEL, effort: str = "low", client=None)` with `.name == f"openai:{model}"`; constructing without `client` creates `openai.OpenAI()` (raises `openai.OpenAIError` if no API key). `extract` always returns one `Candidate` per requested field.

- [ ] **Step 1: Spike — confirm `input_file` + strict `json_schema` work together on `gpt-6.1-sol`**

This calls the real API (costs < $0.01). If `OPENAI_API_KEY` is not set, STOP and ask the user to export it.

`scripts/spike_openai.py`:
```python
"""Throwaway spike: does gpt-6.1-sol accept a PDF input_file together with a strict json_schema?"""
import base64
import json
import sys

from openai import OpenAI

from clef_extractor._pdfgen import build_pdf
from clef_extractor.schema import Field, extraction_json_schema

model = sys.argv[1] if len(sys.argv) > 1 else "gpt-6.1-sol"
fields = [Field("total", "number", "Grand total including tax", True),
          Field("invoice_date", "date", "Invoice issue date", True)]
pdf = build_pdf([[("ACME SARL - FACTURE N° 2026-1042", 16), ("Date: 03/10/2026", 11),
                  ("Sous-total HT: 1.000,00 EUR", 11, 300), ("TVA 20%: 200,00 EUR", 11, 300),
                  ("Total TTC: 1.200,00 EUR", 11, 300)]])
resp = OpenAI().responses.create(
    model=model,
    reasoning={"effort": "low"},
    input=[{"role": "user", "content": [
        {"type": "input_file", "filename": "spike.pdf",
         "file_data": "data:application/pdf;base64," + base64.b64encode(pdf).decode()},
        {"type": "input_text", "text": "Extract: total (grand total including tax), invoice_date. "
                                       "raw exactly as printed, 1-based page, verbatim quote."},
    ]}],
    text={"format": {"type": "json_schema", "name": "extraction", "strict": True,
                     "schema": extraction_json_schema(fields)}},
)
print(resp.status)
print(json.dumps(json.loads(resp.output_text), indent=2, ensure_ascii=False))
print(resp.usage)
```

Run: `uv run python scripts/spike_openai.py`
Expected: `completed`, then JSON with `total.raw == "1.200,00 EUR"`, `total.page == 1`, `invoice_date.raw == "03/10/2026"`.

Record the outcome under `## Review` in `tasks/todo.md` (status, the JSON, token usage). Then `rm -r scripts`.
**If the call fails** (400 on `input_file`, or schema rejected): STOP, report the exact error to the user, and propose the fallback (send rendered page PNGs as `{"type": "input_image", "image_url": "data:image/png;base64,..."}` instead of the PDF). Do not continue to Step 2 without the user's decision.

- [ ] **Step 2: Write the failing tests**

`tests/test_openai_extractor.py`:
```python
import base64
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from clef_extractor.extractors.base import Candidate, ExtractionError
from clef_extractor.extractors.openai import OpenAIExtractor
from clef_extractor.schema import Field, extraction_json_schema

FIELDS = [Field("total", "number", "Grand total", True), Field("customer", "string", "Customer name", False)]
PDF = b"%PDF-1.7 fake"


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def fake_client(response=None, error=None):
    return SimpleNamespace(responses=FakeResponses(response, error))


def ok(payload, output=()):
    return SimpleNamespace(status="completed", output_text=json.dumps(payload),
                           output=list(output), incomplete_details=None)


PAYLOAD = {
    "total": {"raw": "1.200,00 EUR", "page": 1, "quote": "Total TTC: 1.200,00 EUR"},
    "customer": {"raw": None, "page": None, "quote": None},
}


def test_request_shape():
    client = fake_client(ok(PAYLOAD))
    OpenAIExtractor(client=client).extract(PDF, "inv.pdf", FIELDS)
    kw = client.responses.kwargs
    assert kw["model"] == "gpt-6.1-sol"
    assert kw["reasoning"] == {"effort": "low"}
    assert kw["text"]["format"] == {"type": "json_schema", "name": "extraction", "strict": True,
                                    "schema": extraction_json_schema(FIELDS)}
    assert kw["instructions"]
    file_part, text_part = kw["input"][0]["content"]
    assert file_part["type"] == "input_file" and file_part["filename"] == "inv.pdf"
    prefix = "data:application/pdf;base64,"
    assert file_part["file_data"].startswith(prefix)
    assert base64.b64decode(file_part["file_data"][len(prefix):]) == PDF
    assert text_part["type"] == "input_text"
    assert "total" in text_part["text"] and "Grand total" in text_part["text"]


def test_parses_candidates():
    result = OpenAIExtractor(client=fake_client(ok(PAYLOAD))).extract(PDF, "inv.pdf", FIELDS)
    assert result == {
        "total": Candidate("total", "1.200,00 EUR", 1, "Total TTC: 1.200,00 EUR"),
        "customer": Candidate("customer", None, None, None),
    }


def test_missing_and_malformed_fields_become_empty_candidates():
    payload = {"total": {"raw": "  ", "page": True, "quote": 5}, "extra": {"raw": "x"}}
    result = OpenAIExtractor(client=fake_client(ok(payload))).extract(PDF, "inv.pdf", FIELDS)
    assert result == {
        "total": Candidate("total", None, None, None),
        "customer": Candidate("customer", None, None, None),
    }


def test_refusal_raises():
    refusal = SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal="I can't help")])
    with pytest.raises(ExtractionError, match="refused: I can't help"):
        OpenAIExtractor(client=fake_client(ok({}, [refusal]))).extract(PDF, "inv.pdf", FIELDS)


def test_incomplete_raises():
    resp = SimpleNamespace(status="incomplete", output_text="", output=[],
                           incomplete_details=SimpleNamespace(reason="max_output_tokens"))
    with pytest.raises(ExtractionError, match="max_output_tokens"):
        OpenAIExtractor(client=fake_client(resp)).extract(PDF, "inv.pdf", FIELDS)


def test_invalid_json_raises():
    resp = SimpleNamespace(status="completed", output_text="nope", output=[], incomplete_details=None)
    with pytest.raises(ExtractionError, match="valid JSON"):
        OpenAIExtractor(client=fake_client(resp)).extract(PDF, "inv.pdf", FIELDS)


def test_api_error_wrapped():
    err = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    with pytest.raises(ExtractionError, match="OpenAI request failed"):
        OpenAIExtractor(client=fake_client(error=err)).extract(PDF, "inv.pdf", FIELDS)


def test_name_reflects_model():
    assert OpenAIExtractor(model="gpt-6-sol", client=fake_client()).name == "openai:gpt-6-sol"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_openai_extractor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clef_extractor.extractors'`

- [ ] **Step 4: Implement the extractor package**

`src/clef_extractor/extractors/__init__.py`:
```python
"""Extractor backends: turn a PDF + field list into candidate values."""
```

`src/clef_extractor/extractors/base.py`:
```python
"""The extractor interface shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..schema import Field


@dataclass(frozen=True)
class Candidate:
    name: str
    raw: str | None  # value exactly as printed, None if not found
    page: int | None  # 1-based page the extractor claims; verified later
    quote: str | None  # verbatim evidence snippet; verified later


class ExtractionError(Exception):
    """The extractor failed to produce candidates."""


class Extractor(Protocol):
    name: str

    def extract(self, pdf: bytes, filename: str, fields: list[Field]) -> dict[str, Candidate]: ...
```

`src/clef_extractor/extractors/openai.py`:
```python
"""OpenAI Responses API backend (default model: GPT-6.1 Sol)."""

from __future__ import annotations

import base64
import json

import openai

from ..schema import Field, extraction_json_schema
from .base import Candidate, ExtractionError

DEFAULT_MODEL = "gpt-6.1-sol"

INSTRUCTIONS = """You extract field values from PDF documents. For each requested field return:
- raw: the value exactly as printed (keep currency symbols, separators and date format), or null if the document does not contain it. Never guess, compute or reformat values.
- page: the 1-based page number where the value is printed.
- quote: a short verbatim snippet copied from a single line of the document that contains the value, such as its label and the value (at most about 100 characters)."""


def _prompt(fields: list[Field]) -> str:
    lines = [f"- {f.name} ({f.type}{', required' if f.required else ''}): {f.description}" for f in fields]
    return "Fields to extract:\n" + "\n".join(lines)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _candidate(name: str, item: object) -> Candidate:
    if not isinstance(item, dict):
        return Candidate(name, None, None, None)
    page = item.get("page")
    page = page if isinstance(page, int) and not isinstance(page, bool) else None
    return Candidate(name, _text(item.get("raw")), page, _text(item.get("quote")))


class OpenAIExtractor:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "low", client=None):
        self.client = client if client is not None else openai.OpenAI()
        self.model = model
        self.effort = effort
        self.name = f"openai:{model}"

    def extract(self, pdf: bytes, filename: str, fields: list[Field]) -> dict[str, Candidate]:
        file_data = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
        try:
            resp = self.client.responses.create(
                model=self.model,
                reasoning={"effort": self.effort},
                instructions=INSTRUCTIONS,
                input=[{"role": "user", "content": [
                    {"type": "input_file", "filename": filename, "file_data": file_data},
                    {"type": "input_text", "text": _prompt(fields)},
                ]}],
                text={"format": {"type": "json_schema", "name": "extraction", "strict": True,
                                 "schema": extraction_json_schema(fields)}},
            )
        except openai.OpenAIError as e:
            raise ExtractionError(f"OpenAI request failed: {e}") from e

        for item in getattr(resp, "output", None) or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise ExtractionError(f"model refused: {part.refusal}")
        if resp.status != "completed":
            reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
            raise ExtractionError(f"OpenAI response {resp.status}" + (f": {reason}" if reason else ""))
        try:
            data = json.loads(resp.output_text)
        except (TypeError, json.JSONDecodeError) as e:
            raise ExtractionError("model did not return valid JSON") from e
        if not isinstance(data, dict):
            raise ExtractionError("model did not return a JSON object")
        return {f.name: _candidate(f.name, data.get(f.name)) for f in fields}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_openai_extractor.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/clef_extractor/extractors tests/test_openai_extractor.py tasks/todo.md
git commit -m "feat: OpenAI GPT-Sol extractor behind Extractor interface"
```

---

### Task 5: Validator

**Files:**
- Create: `src/clef_extractor/validator.py`
- Test: `tests/test_validator.py`, `tests/test_validator_live.py`

**Interfaces:**
- Consumes: `Field`, `normalize` (Task 1); `Document`, `Location` (Task 2); `ClefClient.ask(state, questions, images) -> dict[str, float]` and `.model` (Task 3); `Candidate` (Task 4).
- Produces:
  - `@dataclass class FieldResult: field: Field; raw: str | None; value: str | float | None; page: int | None; quote: str | None; located: bool = False; scores: dict[str, float] = {}; score: float = 0.0; status: str = "pending"`
  - `class Validator(clef, doc: Document)` with `.clef`, `.validate(field: Field, cand: Candidate) -> FieldResult`
  - Rules: `raw` None → score 0, no clef call. Locate `quote`, then `raw`. Located → page := located page, images [crop, page@100]. Not located but extractor page valid → images [page@100]. Otherwise page := None, score 0, no clef call. Type check fails → `value` None and score forced to 0.

- [ ] **Step 1: Write the failing tests**

`tests/test_validator.py`:
```python
import pytest

from clef_extractor._pdfgen import build_pdf
from clef_extractor.extractors.base import Candidate
from clef_extractor.pdf import Document
from clef_extractor.schema import Field
from clef_extractor.validator import Validator

DOC = Document(build_pdf([
    [("FACTURE N° 2026-1042", 16), ("Date: 03/10/2026", 11), ("Client: Dupont SAS", 11)],
    [("Sous-total HT: 1.000,00 EUR", 11, 300), ("Total TTC: 1.200,00 EUR", 11, 300)],
]))
TOTAL = Field("total", "number", "Grand total including tax", True)


class FakeClef:
    model = "fake-clef"

    def __init__(self, shown=0.9, semantic=0.7):
        self.scores = {"shown": shown, "semantic": semantic}
        self.calls = []

    def ask(self, state, questions, images=()):
        self.calls.append((state, questions, list(images)))
        return {k: self.scores[k] for k in questions}


def test_located_value_corrects_page_and_uses_crop_plus_page():
    clef = FakeClef(shown=0.9, semantic=0.7)
    cand = Candidate("total", "1.200,00 EUR", 1, "Total TTC: 1.200,00 EUR")  # extractor wrongly says page 1
    r = Validator(clef, DOC).validate(TOTAL, cand)
    assert r.located and r.page == 2
    assert r.value == 1200.0
    assert r.scores == {"shown": 0.9, "semantic": 0.7} and r.score == 0.7
    state, questions, images = clef.calls[0]
    assert set(questions) == {"shown", "semantic"}
    assert "'1.200,00 EUR'" in questions["shown"]
    assert "Grand total including tax" in questions["semantic"]
    assert "Grand total including tax" in state and "1.200,00 EUR" in state and "page 2" in state
    assert len(images) == 2 and all(i.startswith(b"\x89PNG") for i in images)


def test_falls_back_to_raw_when_quote_paraphrased():
    clef = FakeClef()
    cand = Candidate("total", "1.200,00 EUR", 2, "The grand total is 1.200,00 EUR")
    r = Validator(clef, DOC).validate(TOTAL, cand)
    assert r.located and r.page == 2
    assert len(clef.calls[0][2]) == 2


def test_not_located_uses_full_page_from_extractor():
    clef = FakeClef()
    r = Validator(clef, DOC).validate(TOTAL, Candidate("total", "9.999,99 EUR", 2, None))
    assert not r.located and r.page == 2
    assert len(clef.calls[0][2]) == 1


@pytest.mark.parametrize("page", [None, 0, 7])
def test_unlocatable_with_invalid_page_scores_zero(page):
    clef = FakeClef()
    r = Validator(clef, DOC).validate(TOTAL, Candidate("total", "9.999,99 EUR", page, "nowhere"))
    assert r.score == 0.0 and r.page is None and r.scores == {}
    assert clef.calls == []


def test_missing_raw_scores_zero_without_calling_clef():
    clef = FakeClef()
    r = Validator(clef, DOC).validate(TOTAL, Candidate("total", None, None, None))
    assert r.raw is None and r.value is None and r.score == 0.0
    assert clef.calls == []


def test_type_failure_forces_zero_score():
    clef = FakeClef(shown=0.95, semantic=0.95)
    r = Validator(clef, DOC).validate(TOTAL, Candidate("total", "Dupont SAS", 1, "Client: Dupont SAS"))
    assert r.value is None and r.score == 0.0
    assert r.scores == {"shown": 0.95, "semantic": 0.95}
```

`tests/test_validator_live.py`:
```python
import pytest

from clef_extractor._pdfgen import build_pdf
from clef_extractor.clef import ClefClient, ClefError
from clef_extractor.extractors.base import Candidate
from clef_extractor.pdf import Document
from clef_extractor.schema import Field
from clef_extractor.validator import Validator

pytestmark = pytest.mark.clef
TOTAL = Field("total", "number", "Grand total including tax (Total TTC)", True)


def invoice(dense: bool) -> list:
    lines = [("ACME SARL - FACTURE N° 2026-1042", 16), ("Date: 03/10/2026", 11)]
    size = 11
    if dense:
        size = 8
        lines += [(f"Ligne {i + 1:02d}  Article ref-{1000 + i}  Qte {i % 7 + 1}  PU {12.5 + i:.2f} EUR", 7)
                  for i in range(40)]
    lines += [("Sous-total HT: 1.000,00 EUR", size, 300), ("TVA 20%: 200,00 EUR", size, 300),
              ("Total TTC: 1.200,00 EUR", size, 300)]
    return [lines]


@pytest.fixture(scope="module")
def clef():
    c = ClefClient()
    try:
        c.health()
    except ClefError as e:
        pytest.skip(str(e))
    return c


@pytest.mark.parametrize("dense", [False, True])
def test_separates_right_from_wrong(clef, dense):
    v = Validator(clef, Document(build_pdf(invoice(dense))))

    def score(raw, quote):
        return v.validate(TOTAL, Candidate("total", raw, 1, quote)).score

    assert score("1.200,00 EUR", "Total TTC: 1.200,00 EUR") > 0.8
    assert score("1.500,00 EUR", None) < 0.1
    assert score("1.000,00 EUR", "Sous-total HT: 1.000,00 EUR") < 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_validator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clef_extractor.validator'`

- [ ] **Step 3: Implement `validator.py`**

`src/clef_extractor/validator.py`:
```python
"""Validate extracted candidates against the rendered PDF page with clef-flash."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .extractors.base import Candidate
from .pdf import Document
from .schema import Field, normalize


@dataclass
class FieldResult:
    field: Field
    raw: str | None
    value: str | float | None
    page: int | None
    quote: str | None
    located: bool = False
    scores: dict[str, float] = dc_field(default_factory=dict)
    score: float = 0.0
    status: str = "pending"


def _state(field: Field, raw: str, page: int) -> str:
    return (f"Document page {page}. Field '{field.name}': {field.description}. "
            f"Extracted value as printed: '{raw}'.")


def _questions(field: Field, raw: str) -> dict[str, str]:
    return {
        "shown": f"Does the image show the value '{raw}'?",
        "semantic": (f"Is '{raw}' the correct value for '{field.description}' according to this document, "
                     f"and not some other value on the page?"),
    }


class Validator:
    def __init__(self, clef, doc: Document):
        self.clef = clef
        self.doc = doc

    def validate(self, field: Field, cand: Candidate) -> FieldResult:
        result = FieldResult(field, cand.raw, None, cand.page, cand.quote)
        if cand.raw is None:
            return result
        try:
            result.value = normalize(field.type, cand.raw)
            type_ok = True
        except ValueError:
            type_ok = False

        loc = self.doc.locate(cand.quote, cand.page) or self.doc.locate(cand.raw, cand.page)
        if loc:
            result.page, result.located = loc.page, True
            images = [self.doc.render_crop(loc.page, loc.bbox), self.doc.render_page(loc.page)]
        elif self.doc.valid_page(cand.page):
            images = [self.doc.render_page(cand.page)]
        else:
            result.page = None
            return result

        result.scores = self.clef.ask(_state(field, cand.raw, result.page), _questions(field, cand.raw), images)
        result.score = min(result.scores.values()) if type_ok else 0.0
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_validator.py -q` → all PASS.
Run: `uv run pytest tests/test_validator_live.py -m clef -q` → PASS with Ollama running.
If a live assertion fails, do **not** loosen the bounds: report the actual scores (print them) to the user — it's calibration data for the question wording.

- [ ] **Step 5: Commit**

```bash
git add src/clef_extractor/validator.py tests/test_validator.py tests/test_validator_live.py tasks/todo.md
git commit -m "feat: clef-flash validator with evidence location and page correction"
```

---

### Task 6: Gate + interactive review

**Files:**
- Create: `src/clef_extractor/gate.py`, `src/clef_extractor/review_cli.py`
- Test: `tests/test_gate.py`, `tests/test_review_cli.py`

**Interfaces:**
- Consumes: `FieldResult` (Task 5); `Field`, `normalize` (Task 1); `Document.render_page`, `.valid_page` (Task 2).
- Produces:
  - `@dataclass(frozen=True) class Decision: action: Literal["accept", "correct", "skip"]; raw: str | None = None; value: str | float | None = None`
  - `Reviewer = Callable[[FieldResult], Decision]`
  - `apply_gate(results: list[FieldResult], threshold: float, reviewer: Reviewer) -> bool` — sets each `status`, returns `complete`.
  - `class CliReviewer(doc: Document, input_fn: Callable[[], str] = input, out: TextIO | None = None, opener: Callable[[str], None] | None = None)` — callable as a `Reviewer`. Writes prompts to `out` (default `sys.stderr`) so stdout stays clean JSON.

- [ ] **Step 1: Write the failing gate tests**

`tests/test_gate.py`:
```python
from clef_extractor.gate import Decision, apply_gate
from clef_extractor.schema import Field
from clef_extractor.validator import FieldResult


def result(required=True, raw="x", score=0.9):
    return FieldResult(Field("f", "string", "desc", required), raw=raw, value=raw, page=1, quote=None, score=score)


class Scripted:
    def __init__(self, decision):
        self.decision, self.seen = decision, []

    def __call__(self, r):
        self.seen.append(r)
        return self.decision


def test_passing_field_is_valid_and_not_reviewed():
    r, reviewer = result(score=0.9), Scripted(Decision("skip"))
    assert apply_gate([r], 0.5, reviewer) is True
    assert r.status == "valid" and reviewer.seen == []


def test_threshold_is_inclusive():
    r = result(score=0.5)
    apply_gate([r], 0.5, Scripted(Decision("skip")))
    assert r.status == "valid"


def test_optional_failures_are_not_reviewed():
    low, absent, reviewer = result(False, score=0.1), result(False, raw=None, score=0.0), Scripted(Decision("skip"))
    assert apply_gate([low, absent], 0.5, reviewer) is True
    assert low.status == "needs_review" and absent.status == "missing"
    assert reviewer.seen == []


def test_required_low_score_accepted():
    r = result(score=0.1)
    assert apply_gate([r], 0.5, Scripted(Decision("accept"))) is True
    assert r.status == "user_confirmed"


def test_required_corrected():
    r = result(score=0.1)
    assert apply_gate([r], 0.5, Scripted(Decision("correct", raw="New", value="New"))) is True
    assert r.status == "user_corrected" and r.raw == "New" and r.value == "New"


def test_required_skipped_makes_incomplete():
    low, absent = result(score=0.1), result(raw=None, score=0.0)
    assert apply_gate([low, absent], 0.5, Scripted(Decision("skip"))) is False
    assert low.status == "needs_review" and absent.status == "missing"
```

- [ ] **Step 2: Write the failing review CLI tests**

`tests/test_review_cli.py`:
```python
import io

import pytest

from clef_extractor._pdfgen import build_pdf
from clef_extractor.gate import Decision
from clef_extractor.pdf import Document
from clef_extractor.review_cli import CliReviewer
from clef_extractor.schema import Field
from clef_extractor.validator import FieldResult

DOC = Document(build_pdf([[("Sous-total HT: 1.000,00 EUR", 11), ("Total TTC: 1.200,00 EUR", 11)]]))
TOTAL = Field("total", "number", "Grand total including tax", True)


def failed(raw="1.000,00 EUR", value=1000.0, page=1):
    return FieldResult(TOTAL, raw=raw, value=value, page=page, quote="Sous-total HT: 1.000,00 EUR",
                       scores={"shown": 0.9, "semantic": 0.12}, score=0.12)


def make(inputs, opener=None):
    it = iter(inputs)

    def input_fn():
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    out = io.StringIO()
    return CliReviewer(DOC, input_fn=input_fn, out=out, opener=opener or (lambda path: None)), out


def test_header_shows_context():
    reviewer, out = make([""])
    reviewer(failed())
    text = out.getvalue()
    for expected in ["total (required)", "0.12", "page 1", '"1.000,00 EUR"', "Sous-total HT", "Grand total"]:
        assert expected in text


def test_enter_accepts():
    reviewer, _ = make([""])
    assert reviewer(failed()) == Decision("accept")


def test_typed_value_corrects():
    reviewer, _ = make(["1.200,00 EUR"])
    assert reviewer(failed()) == Decision("correct", raw="1.200,00 EUR", value=1200.0)


def test_invalid_correction_reprompts():
    reviewer, out = make(["abc", "1200"])
    assert reviewer(failed()) == Decision("correct", raw="1200", value=1200.0)
    assert "Not a valid number" in out.getvalue()


def test_skip():
    reviewer, _ = make(["s"])
    assert reviewer(failed()) == Decision("skip")


def test_eof_skips():
    reviewer, out = make([])
    assert reviewer(failed()) == Decision("skip")
    assert "no input" in out.getvalue()


def test_cannot_accept_missing_value():
    reviewer, out = make(["", "s"])
    assert reviewer(failed(raw=None, value=None, page=None)) == Decision("skip")
    assert "Nothing to accept" in out.getvalue()
    assert "(nothing found)" in out.getvalue()


def test_cannot_accept_type_invalid_value():
    reviewer, out = make(["", "42"])
    assert reviewer(failed(raw="abc", value=None)) == Decision("correct", raw="42", value=42.0)
    assert "not a valid number" in out.getvalue()


def test_open_writes_png_and_calls_opener():
    opened = []
    reviewer, _ = make(["o", ""], opener=opened.append)
    assert reviewer(failed()) == Decision("accept")
    assert len(opened) == 1 and opened[0].endswith(".png")
    with open(opened[0], "rb") as f:
        assert f.read(4) == b"\x89PNG"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_gate.py tests/test_review_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clef_extractor.gate'`

- [ ] **Step 4: Implement `gate.py`**

`src/clef_extractor/gate.py`:
```python
"""Strict gate: decide each field's status; required failures go to a human reviewer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .validator import FieldResult


@dataclass(frozen=True)
class Decision:
    action: Literal["accept", "correct", "skip"]
    raw: str | None = None
    value: str | float | None = None


Reviewer = Callable[[FieldResult], Decision]


def apply_gate(results: list[FieldResult], threshold: float, reviewer: Reviewer) -> bool:
    """Set every result's status. Returns True if no required field was left unresolved."""
    complete = True
    for r in results:
        if r.raw is not None and r.score >= threshold:
            r.status = "valid"
        elif not r.field.required:
            r.status = "missing" if r.raw is None else "needs_review"
        else:
            decision = reviewer(r)
            if decision.action == "accept":
                r.status = "user_confirmed"
            elif decision.action == "correct":
                r.raw, r.value, r.status = decision.raw, decision.value, "user_corrected"
            else:
                r.status = "missing" if r.raw is None else "needs_review"
                complete = False
    return complete
```

- [ ] **Step 5: Implement `review_cli.py`**

`src/clef_extractor/review_cli.py`:
```python
"""Interactive terminal review of required fields that failed validation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import TextIO

from .gate import Decision
from .pdf import Document
from .schema import normalize
from .validator import FieldResult


def _system_open(path: str) -> None:
    subprocess.run(["open", path], check=False)


class CliReviewer:
    def __init__(self, doc: Document, input_fn: Callable[[], str] = input,
                 out: TextIO | None = None, opener: Callable[[str], None] | None = None):
        self.doc = doc
        self.input_fn = input_fn
        self.out = out or sys.stderr
        self.opener = opener or _system_open

    def __call__(self, r: FieldResult) -> Decision:
        self._header(r)
        while True:
            self.out.write("> ")
            self.out.flush()
            try:
                line = self.input_fn().strip()
            except EOFError:
                self._say("\n  (no input available — skipping)")
                return Decision("skip")
            if line == "":
                if r.raw is None:
                    self._say("  Nothing to accept — type the correct value or 's' to skip.")
                    continue
                if r.value is None:
                    self._say(f"  '{r.raw}' is not a valid {r.field.type} — type the correct value or 's' to skip.")
                    continue
                return Decision("accept")
            if line.lower() == "s":
                return Decision("skip")
            if line.lower() == "o":
                self._open_page(r)
                continue
            try:
                value = normalize(r.field.type, line)
            except ValueError:
                self._say(f"  Not a valid {r.field.type}: {line!r}. Try again.")
                continue
            return Decision("correct", raw=line, value=value)

    def _header(self, r: FieldResult) -> None:
        page = r.page if r.page is not None else "?"
        extracted = f'"{r.raw}"' if r.raw is not None else "(nothing found)"
        evidence = f'   evidence: "{r.quote}"' if r.quote else ""
        self._say(f"\n✗ {r.field.name} (required) — confidence {r.score:.2f}, page {page}")
        self._say(f"  {r.field.description}")
        self._say(f"  Extracted: {extracted}{evidence}")
        self._say("  [Enter] accept · type correct value · [s] skip · [o] open page image")

    def _open_page(self, r: FieldResult) -> None:
        page = r.page if self.doc.valid_page(r.page) else 1
        with tempfile.NamedTemporaryFile(prefix=f"{r.field.name}-p{page}-", suffix=".png", delete=False) as f:
            f.write(self.doc.render_page(page, dpi=150))
        self.opener(f.name)
        self._say(f"  opened page {page}: {f.name}")

    def _say(self, text: str) -> None:
        print(text, file=self.out)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_gate.py tests/test_review_cli.py -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/clef_extractor/gate.py src/clef_extractor/review_cli.py tests/test_gate.py tests/test_review_cli.py tasks/todo.md
git commit -m "feat: strict gate with interactive CLI review"
```

---

### Task 7: CLI wiring + README

**Files:**
- Create: `src/clef_extractor/cli.py`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_fields`, `SchemaError` (T1); `Document`, `PdfError` (T2); `ClefClient`, `ClefError` (T3); `OpenAIExtractor`, `ExtractionError`, `DEFAULT_MODEL` (T4); `Validator` (T5); `apply_gate`, `CliReviewer` (T6).
- Produces:
  - `run(doc: Document, fields: list[Field], extractor, validator: Validator, reviewer, threshold: float) -> dict` — the result JSON (spec §6 plus `"file"`).
  - `main(argv: list[str] | None = None) -> int` — exit code 0 / 2 / 1.
  - CLI: `clef-extract PDF --fields FIELDS [--threshold 0.5] [-o OUT] [--model gpt-6.1-sol] [--ollama-url http://localhost:11434]`

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
import io
import json

import pytest

from clef_extractor import cli
from clef_extractor._pdfgen import build_pdf
from clef_extractor.clef import ClefError
from clef_extractor.extractors.base import Candidate


class FakeExtractor:
    name = "fake:model"

    def __init__(self, candidates):
        self.candidates, self.called = candidates, False

    def extract(self, pdf, filename, fields):
        self.called = True
        return self.candidates


class FakeClef:
    model = "clef-flash:9b"

    def __init__(self, score=0.95, healthy=True):
        self.score, self.healthy = score, healthy

    def health(self):
        if not self.healthy:
            raise ClefError("Ollama not reachable")

    def ask(self, state, questions, images=()):
        return {k: self.score for k in questions}


CANDS = {
    "total": Candidate("total", "1.200,00 EUR", 1, "Total TTC: 1.200,00 EUR"),
    "customer": Candidate("customer", "Dupont SAS", 1, "Client: Dupont SAS"),
}


@pytest.fixture
def files(tmp_path):
    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(build_pdf([[("Client: Dupont SAS", 11), ("Total TTC: 1.200,00 EUR", 11)]]))
    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps({
        "total": {"type": "number", "description": "Grand total including tax", "required": True},
        "customer": {"type": "string", "description": "Customer name"},
    }))
    return pdf, fields


def setup(monkeypatch, clef, extractor, stdin=""):
    monkeypatch.setattr(cli, "ClefClient", lambda **kw: clef)
    monkeypatch.setattr(cli, "OpenAIExtractor", lambda **kw: extractor)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))


def test_all_valid_exits_0_and_prints_json(monkeypatch, capsys, files):
    pdf, fields = files
    setup(monkeypatch, FakeClef(0.95), FakeExtractor(CANDS))
    assert cli.main([str(pdf), "--fields", str(fields)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["complete"] is True and out["file"] == "inv.pdf"
    assert out["fields"]["total"] == {"value": 1200.0, "raw": "1.200,00 EUR", "status": "valid",
                                      "score": 0.95, "scores": {"shown": 0.95, "semantic": 0.95}, "page": 1}
    assert out["meta"] == {"extractor": "fake:model", "validator": "clef-flash:9b", "threshold": 0.5}


def test_required_failure_without_input_exits_2(monkeypatch, capsys, files):
    pdf, fields = files
    setup(monkeypatch, FakeClef(0.1), FakeExtractor(CANDS), stdin="")
    assert cli.main([str(pdf), "--fields", str(fields)]) == 2
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["complete"] is False
    assert out["fields"]["total"]["status"] == "needs_review"
    assert out["fields"]["customer"]["status"] == "needs_review"
    assert "total (required)" in captured.err


def test_required_failure_corrected_via_stdin(monkeypatch, capsys, files):
    pdf, fields = files
    setup(monkeypatch, FakeClef(0.1), FakeExtractor(CANDS), stdin="1.250,00 EUR\n")
    assert cli.main([str(pdf), "--fields", str(fields)]) == 0
    total = json.loads(capsys.readouterr().out)["fields"]["total"]
    assert total["status"] == "user_corrected" and total["value"] == 1250.0


def test_output_file(monkeypatch, capsys, files, tmp_path):
    pdf, fields = files
    setup(monkeypatch, FakeClef(0.95), FakeExtractor(CANDS))
    out_path = tmp_path / "out.json"
    assert cli.main([str(pdf), "--fields", str(fields), "-o", str(out_path)]) == 0
    assert capsys.readouterr().out == ""
    assert json.loads(out_path.read_text())["complete"] is True


def test_clef_down_exits_1_before_extraction(monkeypatch, capsys, files):
    pdf, fields = files
    extractor = FakeExtractor(CANDS)
    setup(monkeypatch, FakeClef(healthy=False), extractor)
    assert cli.main([str(pdf), "--fields", str(fields)]) == 1
    assert extractor.called is False
    assert "error: Ollama not reachable" in capsys.readouterr().err


def test_bad_fields_file_exits_1(monkeypatch, capsys, files, tmp_path):
    pdf, _ = files
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    setup(monkeypatch, FakeClef(), FakeExtractor(CANDS))
    assert cli.main([str(pdf), "--fields", str(bad)]) == 1
    assert "non-empty" in capsys.readouterr().err


def test_threshold_out_of_range_rejected(files):
    pdf, fields = files
    with pytest.raises(SystemExit):
        cli.main([str(pdf), "--fields", str(fields), "--threshold", "2"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL — `ImportError: cannot import name 'cli'`

- [ ] **Step 3: Implement `cli.py`**

`src/clef_extractor/cli.py`:
```python
"""Command line entry point: extract → validate → gate → JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import openai

from .clef import ClefClient, ClefError
from .extractors.base import ExtractionError
from .extractors.openai import DEFAULT_MODEL, OpenAIExtractor
from .gate import apply_gate
from .pdf import Document, PdfError
from .review_cli import CliReviewer
from .schema import Field, SchemaError, load_fields
from .validator import Validator


def run(doc: Document, fields: list[Field], extractor, validator: Validator, reviewer, threshold: float) -> dict:
    candidates = extractor.extract(doc.data, doc.name, fields)
    results = [validator.validate(f, candidates[f.name]) for f in fields]
    complete = apply_gate(results, threshold, reviewer)
    return {
        "file": doc.name,
        "complete": complete,
        "fields": {
            r.field.name: {
                "value": r.value,
                "raw": r.raw,
                "status": r.status,
                "score": round(r.score, 4),
                "scores": {k: round(v, 4) for k, v in r.scores.items()},
                "page": r.page,
            }
            for r in results
        },
        "meta": {"extractor": extractor.name, "validator": validator.clef.model, "threshold": threshold},
    }


def _threshold(text: str) -> float:
    value = float(text)
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 1")
    return value


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="clef-extract", description=__doc__)
    p.add_argument("pdf", help="PDF file to extract from")
    p.add_argument("--fields", required=True, help="JSON file defining the fields to extract")
    p.add_argument("--threshold", type=_threshold, default=0.5, help="minimum clef-flash score to accept (0-1)")
    p.add_argument("-o", "--output", help="write result JSON here instead of stdout")
    p.add_argument("--model", default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL), help="OpenAI model")
    p.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama base URL")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        fields = load_fields(args.fields)
        doc = Document.from_path(args.pdf)
        extractor = OpenAIExtractor(model=args.model)
        clef = ClefClient(base_url=args.ollama_url)
        clef.health()  # before any OpenAI spend
        result = run(doc, fields, extractor, Validator(clef, doc), CliReviewer(doc), args.threshold)
    except (SchemaError, PdfError, ClefError, ExtractionError, openai.OpenAIError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all PASS (whole suite, live tests deselected).

- [ ] **Step 5: Write `README.md`**

````markdown
# clef-pdf-extractor

Extract fields from any PDF with OpenAI GPT-6.1 Sol, validate every value locally with
[clef-flash](https://ollama.com/library/clef-flash), and get asked about any required field that fails.

## Setup

```bash
ollama pull clef-flash:9b      # local validator
export OPENAI_API_KEY=sk-...   # extractor
uv sync
```

## Usage

```bash
uv run clef-extract invoice.pdf --fields fields.json -o result.json
```

`fields.json`:
```json
{
  "invoice_total": {"type": "number", "description": "Grand total including tax", "required": true},
  "invoice_date":  {"type": "date",   "description": "Invoice issue date",        "required": true},
  "supplier_name": {"type": "string", "description": "Legal name of the issuer"}
}
```

Options: `--threshold 0.5` (minimum clef-flash score), `--model gpt-6.1-sol` (or `OPENAI_MODEL`),
`--ollama-url http://localhost:11434`.

When a required field fails, you're prompted: Enter accepts, typing replaces the value, `s` skips, `o` opens the page.
Exit codes: 0 complete, 2 a required field was skipped, 1 error.

## Tests

```bash
uv run pytest               # unit tests, no network
uv run pytest -m clef       # needs Ollama with clef-flash:9b
uv run pytest -m e2e        # needs OPENAI_API_KEY + Ollama; costs money
```

## Calibration

```bash
uv run python eval/make_samples.py
uv run python eval/calibrate.py
```
````

- [ ] **Step 6: Manual smoke run (needs Ollama + `OPENAI_API_KEY`)**

```bash
uv run python -c "
from pathlib import Path
from clef_extractor._pdfgen import build_pdf
Path('/tmp/smoke.pdf').write_bytes(build_pdf([[('ACME SARL - FACTURE N° 2026-1042', 16), ('Date: 03/10/2026', 11), ('Sous-total HT: 1.000,00 EUR', 11, 300), ('TVA 20%: 200,00 EUR', 11, 300), ('Total TTC: 1.200,00 EUR', 11, 300)]]))
Path('/tmp/smoke-fields.json').write_text('{\"total\": {\"type\": \"number\", \"description\": \"Grand total including tax\", \"required\": true}, \"invoice_date\": {\"type\": \"date\", \"description\": \"Invoice issue date\", \"required\": true}}')
"
uv run clef-extract /tmp/smoke.pdf --fields /tmp/smoke-fields.json; echo "exit=$?"
```
Expected: JSON with `total.value == 1200.0`, `invoice_date.value == "2026-10-03"`, both `valid`, `exit=0`.

- [ ] **Step 7: Commit**

```bash
git add src/clef_extractor/cli.py README.md tests/test_cli.py tasks/todo.md
git commit -m "feat: clef-extract CLI wiring, exit codes and README"
```

---

### Task 8: Calibration set, calibration script and end-to-end test

**Files:**
- Create: `src/clef_extractor/calibration.py`, `eval/make_samples.py`, `eval/calibrate.py`
- Test: `tests/test_calibration.py`, `tests/test_e2e.py`

**Interfaces:**
- Consumes: `build_pdf` (T2); `Document` (T2); `ClefClient` (T3); `Candidate`, `OpenAIExtractor` (T4); `Validator` (T5); `Decision` (T6); `run` (T7); `Field`, `parse_fields`, `normalize` (T1).
- Produces:
  - `@dataclass(frozen=True) class Trial: sample: str; field: str; raw: str; truthful: bool; score: float; located: bool`
  - `@dataclass(frozen=True) class ThresholdStats: threshold: float; false_accepts: int; false_flags: int; wrong_total: int; true_total: int` with `.false_accept_rate`, `.false_flag_rate`
  - `THRESHOLDS = (0.1, 0.2, …, 0.9)`; `summarize(trials, thresholds=THRESHOLDS) -> list[ThresholdStats]`; `recommend(stats) -> ThresholdStats`
  - Sample files in `eval/samples/`: `<name>.pdf`, `<name>.truth.json` (`{"pdf", "fields": {name: {type, description, required, raw, page, wrong: [...]}}}`), `<name>.fields.json` (CLI field defs).

- [ ] **Step 1: Write the failing calibration tests**

`tests/test_calibration.py`:
```python
from clef_extractor.calibration import ThresholdStats, Trial, recommend, summarize


def trial(truthful, score):
    return Trial("s", "f", "v", truthful, score, True)


def test_summarize_counts_errors_per_threshold():
    trials = [trial(True, 0.95), trial(True, 0.45), trial(False, 0.02), trial(False, 0.6)]
    stats = {s.threshold: s for s in summarize(trials, thresholds=(0.3, 0.5, 0.7))}
    assert stats[0.3] == ThresholdStats(0.3, false_accepts=1, false_flags=0, wrong_total=2, true_total=2)
    assert stats[0.5] == ThresholdStats(0.5, false_accepts=1, false_flags=1, wrong_total=2, true_total=2)
    assert stats[0.7] == ThresholdStats(0.7, false_accepts=0, false_flags=1, wrong_total=2, true_total=2)
    assert stats[0.5].false_accept_rate == 0.5 and stats[0.5].false_flag_rate == 0.5


def test_recommend_prefers_zero_false_accepts_then_fewest_flags_then_higher_threshold():
    stats = [ThresholdStats(0.3, 1, 0, 2, 2), ThresholdStats(0.5, 0, 1, 2, 2),
             ThresholdStats(0.6, 0, 1, 2, 2), ThresholdStats(0.9, 0, 2, 2, 2)]
    assert recommend(stats).threshold == 0.6


def test_recommend_falls_back_to_fewest_false_accepts():
    stats = [ThresholdStats(0.3, 2, 0, 2, 2), ThresholdStats(0.7, 1, 1, 2, 2)]
    assert recommend(stats).threshold == 0.7


def test_rates_handle_empty_sets():
    s = ThresholdStats(0.5, 0, 0, 0, 0)
    assert s.false_accept_rate == 0.0 and s.false_flag_rate == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_calibration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clef_extractor.calibration'`

- [ ] **Step 3: Implement `calibration.py`**

`src/clef_extractor/calibration.py`:
```python
"""Threshold calibration math: false accepts (wrong value passes) vs false flags (true value fails)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

THRESHOLDS: tuple[float, ...] = tuple(round(0.1 * i, 1) for i in range(1, 10))


@dataclass(frozen=True)
class Trial:
    sample: str
    field: str
    raw: str
    truthful: bool
    score: float
    located: bool


@dataclass(frozen=True)
class ThresholdStats:
    threshold: float
    false_accepts: int
    false_flags: int
    wrong_total: int
    true_total: int

    @property
    def false_accept_rate(self) -> float:
        return self.false_accepts / self.wrong_total if self.wrong_total else 0.0

    @property
    def false_flag_rate(self) -> float:
        return self.false_flags / self.true_total if self.true_total else 0.0


def summarize(trials: Iterable[Trial], thresholds: Sequence[float] = THRESHOLDS) -> list[ThresholdStats]:
    trials = list(trials)
    wrong = [t for t in trials if not t.truthful]
    true = [t for t in trials if t.truthful]
    return [
        ThresholdStats(
            threshold=th,
            false_accepts=sum(t.score >= th for t in wrong),
            false_flags=sum(t.score < th for t in true),
            wrong_total=len(wrong),
            true_total=len(true),
        )
        for th in thresholds
    ]


def recommend(stats: Sequence[ThresholdStats]) -> ThresholdStats:
    """Zero false accepts first; then fewest false flags; ties → the higher (safer) threshold."""
    safe = [s for s in stats if s.false_accepts == 0]
    if safe:
        return min(safe, key=lambda s: (s.false_flags, -s.threshold))
    return min(stats, key=lambda s: (s.false_accepts, s.false_flags))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_calibration.py -q`
Expected: all PASS.

- [ ] **Step 5: Write the sample generator**

`eval/make_samples.py`:
```python
"""Generate the calibration set: synthetic PDFs + ground truth with adversarial wrong values.

Usage: uv run python eval/make_samples.py [--out eval/samples]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from clef_extractor._pdfgen import build_pdf


def f(type_, description, raw, wrong, page=1, required=True):
    return {"type": type_, "description": description, "required": required,
            "raw": raw, "page": page, "wrong": wrong}


FR_INVOICE = [[
    ("ACME SARL - FACTURE N° 2026-1042", 16), ("Date: 03/10/2026", 11), ("Client: Dupont SAS", 11), ("", 11),
    ("Sous-total HT: 1.000,00 EUR", 11, 300), ("TVA 20%: 200,00 EUR", 11, 300), ("Total TTC: 1.200,00 EUR", 11, 300),
]]
FR_INVOICE_FIELDS = {
    "invoice_number": f("string", "Invoice number", "2026-1042", ["2026-1024", "2025-1042"]),
    "invoice_date": f("date", "Invoice issue date", "03/10/2026", ["10/03/2026", "03/10/2025"]),
    "total": f("number", "Grand total including tax (TTC)", "1.200,00 EUR", ["1.000,00 EUR", "200,00 EUR", "1.020,00 EUR"]),
    "customer_name": f("string", "Name of the customer being billed", "Dupont SAS", ["ACME SARL"]),
}

FR_DENSE = [[("ACME SARL - FACTURE N° 2026-2077", 16), ("Date: 15/09/2026", 11)]
            + [(f"Ligne {i + 1:02d}  Article ref-{1000 + i}  Qte {i % 7 + 1}  PU {12.5 + i:.2f} EUR  "
                f"Total {(i % 7 + 1) * (12.5 + i):.2f} EUR", 7) for i in range(40)]
            + [("Sous-total HT: 4.310,50 EUR", 8, 300), ("TVA 20%: 862,10 EUR", 8, 300),
               ("Total TTC: 5.172,60 EUR", 8, 300)]]
FR_DENSE_FIELDS = {
    "invoice_date": f("date", "Invoice issue date", "15/09/2026", ["09/15/2025", "15/09/2025"]),
    "total": f("number", "Grand total including tax (TTC)", "5.172,60 EUR", ["4.310,50 EUR", "862,10 EUR", "5.127,60 EUR"]),
    "vat_amount": f("number", "VAT amount (TVA)", "862,10 EUR", ["5.172,60 EUR", "826,10 EUR"]),
}

US_INVOICE = [[
    ("Globex Inc. - INVOICE #INV-7781", 16), ("Invoice date: October 3, 2026", 11),
    ("Due date: November 2, 2026", 11), ("Bill to: Initech LLC", 11), ("", 11),
    ("Subtotal: $2,450.00", 11, 300), ("Sales tax (8.25%): $202.13", 11, 300), ("Total due: $2,652.13", 11, 300),
]]
US_INVOICE_FIELDS = {
    "invoice_number": f("string", "Invoice number", "INV-7781", ["INV-7718"]),
    "due_date": f("date", "Payment due date", "November 2, 2026", ["October 3, 2026", "November 20, 2026"]),
    "total": f("number", "Total amount due including tax", "$2,652.13", ["$2,450.00", "$202.13", "$2,625.13"]),
    "customer_name": f("string", "Name of the customer being billed", "Initech LLC", ["Globex Inc."]),
}

US_RECEIPT = [[
    ("CORNER CAFE", 16), ("Receipt 0042", 11), ("2026-09-28 08:14", 11), ("", 11),
    ("Latte 4.50", 11), ("Croissant 3.25", 11), ("Orange juice 3.75", 11), ("", 11),
    ("Subtotal 11.50", 11, 300), ("Tax 0.95", 11, 300), ("TOTAL 12.45", 11, 300), ("Paid VISA ****4242", 11),
]]
US_RECEIPT_FIELDS = {
    "date": f("date", "Purchase date", "2026-09-28", ["2026-09-29", "2026-08-28"]),
    "total": f("number", "Total paid", "12.45", ["11.50", "0.95", "12.54"]),
    "card_last4": f("string", "Last 4 digits of the payment card", "4242", ["4224", "0042"]),
}

FR_FORM = [[
    ("FORMULAIRE D'INSCRIPTION", 16), ("Nom: Martin", 11), ("Prénom: Claire", 11),
    ("Date de naissance: 14/02/1990", 11), ("Ville: Lyon", 11), ("Code postal: 69003", 11),
]]
FR_FORM_FIELDS = {
    "last_name": f("string", "Family name (nom)", "Martin", ["Claire"]),
    "birth_date": f("date", "Date of birth", "14/02/1990", ["14/02/1991", "12/04/1990"]),
    "postal_code": f("string", "Postal code", "69003", ["69300", "69030"]),
}

TWO_PAGE = [
    [("Initech LLC - INVOICE #A-501", 16), ("Date: 2026-08-01", 11)]
    + [(f"Item {i + 1:02d}  consulting hours  {i + 2} h  $150.00", 9) for i in range(30)],
    [("Subtotal: $9,900.00", 11, 300), ("Tax: $0.00", 11, 300), ("Total: $9,900.00", 11, 300)],
]
TWO_PAGE_FIELDS = {
    "invoice_date": f("date", "Invoice issue date", "2026-08-01", ["2026-01-08"]),
    "total": f("number", "Grand total", "$9,900.00", ["$9,090.00", "$150.00"], page=2),
}

SAMPLES = [
    ("fr_invoice_sparse", FR_INVOICE, FR_INVOICE_FIELDS, False),
    ("fr_invoice_dense", FR_DENSE, FR_DENSE_FIELDS, False),
    ("us_invoice", US_INVOICE, US_INVOICE_FIELDS, False),
    ("us_receipt", US_RECEIPT, US_RECEIPT_FIELDS, False),
    ("fr_form", FR_FORM, FR_FORM_FIELDS, False),
    ("two_page_invoice", TWO_PAGE, TWO_PAGE_FIELDS, False),
    ("fr_invoice_scanned", FR_INVOICE, FR_INVOICE_FIELDS, True),
    ("us_receipt_scanned", US_RECEIPT, US_RECEIPT_FIELDS, True),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent / "samples"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    for name, pages, fields, image_only in SAMPLES:
        (out / f"{name}.pdf").write_bytes(build_pdf(pages, image_only=image_only))
        (out / f"{name}.truth.json").write_text(
            json.dumps({"pdf": f"{name}.pdf", "fields": fields}, indent=2, ensure_ascii=False))
        defs = {k: {"type": v["type"], "description": v["description"], "required": v["required"]}
                for k, v in fields.items()}
        (out / f"{name}.fields.json").write_text(json.dumps(defs, indent=2, ensure_ascii=False))
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
```

Run: `uv run python eval/make_samples.py`
Expected: 8 `wrote …` lines; `eval/samples/` has 24 files.

- [ ] **Step 6: Write the calibration script**

`eval/calibrate.py`:
```python
"""Score true and adversarial wrong values with clef-flash; report error rates per threshold.

Usage: uv run python eval/calibrate.py [--samples eval/samples] [--csv eval/results.csv]
No OpenAI calls: candidates come from the ground truth.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from clef_extractor.calibration import Trial, recommend, summarize
from clef_extractor.clef import ClefClient
from clef_extractor.extractors.base import Candidate
from clef_extractor.pdf import Document
from clef_extractor.schema import Field
from clef_extractor.validator import Validator


def collect(samples: Path, clef: ClefClient) -> list[Trial]:
    trials = []
    for truth_path in sorted(samples.glob("*.truth.json")):
        truth = json.loads(truth_path.read_text())
        sample = truth_path.name.removesuffix(".truth.json")
        doc = Document.from_path(samples / truth["pdf"])
        validator = Validator(clef, doc)
        for name, spec in truth["fields"].items():
            field = Field(name, spec["type"], spec["description"], spec["required"])
            for raw, truthful in [(spec["raw"], True)] + [(w, False) for w in spec["wrong"]]:
                # Quote = the raw value: a wrong value that is printed elsewhere (e.g. the subtotal)
                # gets located there, just as a real extractor's quote would be.
                r = validator.validate(field, Candidate(name, raw, spec["page"], raw))
                trials.append(Trial(sample, name, raw, truthful, r.score, r.located))
                print(f"{sample:22} {name:16} {'TRUE ' if truthful else 'wrong'} {raw:22} {r.score:.3f}")
    return trials


def main() -> None:
    here = Path(__file__).parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(here / "samples"))
    ap.add_argument("--csv", default=str(here / "results.csv"))
    args = ap.parse_args()

    clef = ClefClient()
    clef.health()
    trials = collect(Path(args.samples), clef)

    with open(args.csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sample", "field", "raw", "truthful", "score", "located"])
        for t in trials:
            w.writerow([t.sample, t.field, t.raw, t.truthful, f"{t.score:.4f}", t.located])

    stats = summarize(trials)
    print("\nthreshold  false_accepts  false_flags")
    for s in stats:
        print(f"  {s.threshold:.1f}      {s.false_accepts:3}/{s.wrong_total} ({s.false_accept_rate:5.1%})"
              f"   {s.false_flags:3}/{s.true_total} ({s.false_flag_rate:5.1%})")
    best = recommend(stats)
    print(f"\nrecommended threshold: {best.threshold:.1f} "
          f"(false accepts {best.false_accept_rate:.1%}, false flags {best.false_flag_rate:.1%})")
    print("target: 0 false accepts, < 10% false flags")

    print("\nhighest-scoring wrong values:")
    for t in sorted((t for t in trials if not t.truthful), key=lambda t: -t.score)[:5]:
        print(f"  {t.score:.3f}  {t.sample}/{t.field} = {t.raw}")
    print("lowest-scoring true values:")
    for t in sorted((t for t in trials if t.truthful), key=lambda t: t.score)[:5]:
        print(f"  {t.score:.3f}  {t.sample}/{t.field} = {t.raw}")


if __name__ == "__main__":
    main()
```

Run (Ollama running): `uv run python eval/calibrate.py`
Expected: a per-trial log, the threshold table, a recommended threshold and the worst offenders. Paste the table and recommendation into `tasks/todo.md` under `## Review`. If the target is missed, report it to the user with the worst offenders; do not change the default threshold or question wording without their agreement.

- [ ] **Step 7: Write the end-to-end test**

`tests/test_e2e.py`:
```python
"""Full pipeline against real OpenAI + local clef-flash. Costs money: run with `-m e2e`."""

import json
from pathlib import Path

import pytest

from clef_extractor.cli import run
from clef_extractor.clef import ClefClient
from clef_extractor.extractors.openai import OpenAIExtractor
from clef_extractor.gate import Decision
from clef_extractor.pdf import Document
from clef_extractor.schema import normalize, parse_fields
from clef_extractor.validator import Validator

pytestmark = pytest.mark.e2e
SAMPLES = Path(__file__).resolve().parent.parent / "eval" / "samples"


@pytest.mark.parametrize("name", ["fr_invoice_sparse", "us_invoice", "fr_invoice_scanned"])
def test_pipeline_end_to_end(name):
    truth_path = SAMPLES / f"{name}.truth.json"
    if not truth_path.exists():
        pytest.skip("run: uv run python eval/make_samples.py")
    truth = json.loads(truth_path.read_text())
    fields = parse_fields(json.loads((SAMPLES / f"{name}.fields.json").read_text()))
    doc = Document.from_path(SAMPLES / truth["pdf"])
    clef = ClefClient()
    clef.health()
    asked = []

    def reviewer(r):
        asked.append((r.field.name, r.raw, r.score))
        return Decision("skip")

    result = run(doc, fields, OpenAIExtractor(), Validator(clef, doc), reviewer, 0.5)
    assert asked == [], f"unexpected review prompts: {asked}"
    assert result["complete"] is True
    for field_name, spec in truth["fields"].items():
        assert result["fields"][field_name]["value"] == normalize(spec["type"], spec["raw"])
```

Run: `uv run pytest -m e2e -q` (needs `OPENAI_API_KEY` + Ollama; ~3 OpenAI calls)
Expected: 3 PASS. A failure here is a finding, not a test to weaken: report which field, the raw value and the score.

- [ ] **Step 8: Final verification and commit**

Run: `uv run pytest -q && uv run pytest -m clef -q`
Expected: all PASS.

Fill `## Review` in `tasks/todo.md`: spike result, calibration table + recommended threshold, e2e result, anything that deviated from the plan.

```bash
git add src/clef_extractor/calibration.py eval/make_samples.py eval/calibrate.py tests/test_calibration.py tests/test_e2e.py tasks/todo.md
git commit -m "feat: calibration set, threshold calibration and end-to-end test"
```
