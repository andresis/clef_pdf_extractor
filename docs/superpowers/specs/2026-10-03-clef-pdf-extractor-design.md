# clef-pdf-extractor — Design

**Date:** 2026-10-03
**Status:** Draft, awaiting user review

## 1. Goal

Extract field values from **any PDF**, where the fields to extract are declared per request. A cloud LLM served through Ollama (**gemma4:31b-cloud**) extracts candidate values; a **local** decision model, **clef-flash:9b** (Ollama), validates each value against the rendered PDF page. Any **required** field that fails validation is put to the user in an **interactive CLI** before the result is accepted.

**Success:** every required field in the output is either confirmed by clef-flash or confirmed/corrected by a human. Wrong values are caught, not silently accepted.

### Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Document scope | Any PDF; fields defined per request |
| Extractor | Ollama cloud model `gemma4:31b-cloud` (configurable) behind an `Extractor` interface; OpenAI GPT-6.1 Sol backend written but commented out |
| Validator | clef-flash:9b via local Ollama `POST /v1/systemone` |
| Validation evidence | Page image (crop around located evidence + downscaled full page) |
| Failure policy | Strict gate: failed/missing **required** field → ask the user |
| Interface | Interactive CLI |
| Field shapes | Scalar values only (string, number, date) |
| Language | Python |

*Revised 2026-10-03: extractor switched from Claude Opus 5.5 to OpenAI GPT-6.1 Sol. Revised 2026-10-04: switched to Ollama `gemma4:31b-cloud`; OpenAI code kept commented out.*

### Non-goals (v1)

Tables / line items, additional extractor backends (e.g. Claude), web UI, batch processing of many PDFs, fine-tuning clef-flash, multi-user / auth.

## 2. Background: verified facts about clef-flash

- clef-flash is a **decision model**, not a generator (`output_tokens: 0`). Input: `state` (text), optional `images` (base64 PNG/JPEG/WebP, no URLs), and named `questions`. Question types: `noul` (boolean probability), `choice` (2–26 candidates, given as a `criteria` map `{key: description}`), `score`.
- Endpoint: `POST http://localhost:11434/v1/systemone`. Response: `{"answers": {name: {"type": "noul", "noul": p}}}`.
- Probe results on synthetic French-format invoices (2026-10-03):

| Input | right total | wrong total | subtotal-as-total | right date | wrong date |
|---|---|---|---|---|---|
| sparse page, full @100–150dpi | 0.97 | 0.008 | 0.013 | 0.97 | 0.014 |
| dense (7pt, 40 rows), full page | 0.89–0.91 | 0.014 | 0.02–0.04 | 0.97 | 0.014 |
| dense, crop around total | 0.92 | 0.012 | 0.022 | 0.007* | 0.022 |

\* The date was outside the crop: clef-flash correctly reported it not shown. Crops must contain the field's own evidence.

Second probe with the exact §4.3 request (two images: crop + full page; `shown`/`semantic`; score = min): right value 0.96 (sparse and dense), wrong value 0.017 / 0.06, subtotal-as-total 0.013 / 0.046. Two images are accepted and stay around 2k input tokens.

## 3. Architecture

```
fields.json + doc.pdf
   │
   ├─▶ extractors/ollama.py ──▶ {name: Candidate(raw, value, page, quote)}
   │
   ├─▶ pdf.py: search_for(quote) → real page + bbox; render crop + full page
   │
   ├─▶ validator.py: clef-flash questions per field → scores
   │
   ├─▶ gate.py: decide status; required failures → review_cli.py
   │
   └─▶ result.json
```

### Units

| File | Responsibility | Depends on |
|---|---|---|
| `schema.py` | Load `fields.json`; build the JSON schema for the extractor; type-check and normalize values (numbers in `1.200,00` / `1,200.00` styles, dates in common formats → ISO) | — |
| `pdf.py` | Open/validate the PDF; render pages and crops to PNG; `locate(quote, hint_page)` → `(page, bbox) \| None`; detect pages with no text layer | pymupdf |
| `extractors/base.py` | `Extractor` protocol: `extract(doc: Document, fields: list[Field]) -> dict[str, Candidate]`; shared prompt | — |
| `extractors/ollama.py` | Ollama backend: page text (+ images for vision models), JSON schema `format`, lenient parsing | `httpx` |
| `extractors/openai.py` | OpenAI backend — commented out | (`openai`, not installed) |
| `clef.py` | Thin client for `/v1/systemone`; health check | `httpx` |
| `validator.py` | For each candidate: locate evidence, build images, ask clef-flash, produce `FieldResult` with scores | `pdf`, `clef` |
| `gate.py` | Apply gate rules (§5); invoke review for required failures | `review_cli` |
| `review_cli.py` | Interactive per-field prompt | stdlib `input` |
| `cli.py` | `extract <pdf> --fields <fields.json> [--threshold 0.5] [-o out.json]` | all |

### Field definition file

```json
{
  "invoice_total": {"type": "number", "description": "Grand total including tax", "required": true},
  "invoice_date":  {"type": "date",   "description": "Invoice issue date",        "required": true},
  "supplier_name": {"type": "string", "description": "Legal name of the issuer",  "required": false}
}
```

## 4. Data flow

### 4.1 Extraction (Ollama cloud model, default `gemma4:31b-cloud`)

- `POST /api/chat` on the local Ollama (which proxies cloud models), model `gemma4:31b-cloud` (overridable via `--model` / `EXTRACT_MODEL`), `stream: false`, `think: false`, `temperature: 0`, JSON schema from `schema.py` in `format`.
- Ollama does not accept PDF files, so the user message carries every page's **text layer** under `=== Page N ===` headers, plus **page images** (100 dpi) when the model reports the `vision` capability (`POST /api/show`). Scanned pages therefore work only with vision models.
- Lenient parsing: gemma4 was observed (2026-10-04) to ignore `format` and return a fenced JSON list of `{field, raw, page, quote}`; the parser accepts that and the `{name: {...}}` object form.
- Per field: `raw` (string exactly as printed, or null), `page` (1-based int), `quote` (short verbatim snippet containing the value). The validator normalizes `raw` → `value`.
- Evidence is self-reported (`quote`, `page`) and verified locally (§4.2) — the extractor is not trusted for page numbers.
- Probe results (dense French invoice): gemma4:31b-cloud got all fields right on the digital and the scanned version (scan: dropped "EUR" from `raw`). `glm-5.3:cloud` and `deepseek-v4.1-flash:cloud` require Ollama Pro; `nemotron-3-super:cloud` (free, text-only) returned the supplier as the customer and found nothing on the scan.
- The OpenAI GPT-6.1 Sol backend (Responses API, PDF `input_file`, strict `json_schema`) is written in `extractors/openai.py` but **commented out**.

```python
Candidate(name, raw: str | None, value, page: int | None, quote: str | None)
```

### 4.2 Locate evidence (no model)

`pdf.locate(quote, hint_page)`: search the hint page first, then all pages, using pymupdf `search_for`. If found → actual page + bbox (overrides the extractor's page). If not found (scanned PDF or paraphrased quote) → fall back to the extractor's page with no bbox. If that page is invalid → field fails validation.

### 4.3 Validation (clef-flash)

Images:
- **Located:** crop of the page around bbox (full page width, ±150pt vertically, 150 dpi) **plus** full page downscaled (100 dpi) so the model sees context (total vs subtotal).
- **Not located:** full page at 100 dpi.

Request per field (fields sharing identical images may be batched into one request):

```json
{
  "model": "clef-flash:9b",
  "state": "Document page {p}. Field '{name}': {description}. Extracted value as printed: '{raw}'.",
  "images": ["<crop>", "<page>"],
  "questions": {
    "{name}__shown":    {"type": "noul", "instructions": "Does the image show the value '{raw}'?"},
    "{name}__semantic": {"type": "noul", "instructions": "Is '{raw}' the correct value for '{description}' according to this document, and not some other value on the page?"}
  }
}
```

`score = min(shown, semantic)`. Pass iff `score >= threshold` (default 0.5; set by calibration, §8.2).

```python
FieldResult(name, value, raw, page, located: bool, bbox, scores: dict, score: float, status)
status ∈ {"valid", "user_confirmed", "user_corrected", "needs_review", "missing"}
```

## 5. Gate rules

| Situation | Required field | Optional field |
|---|---|---|
| score ≥ threshold | `valid` | `valid` |
| score < threshold | **ask user** | `needs_review` (no prompt) |
| Extractor returned null | **ask user** (empty default) | `missing` |
| Value fails type check | score := 0 → **ask user** | `needs_review` |

### Review prompt

```
✗ invoice_total (required) — confidence 0.12, page 1
  Extracted: "1.000,00 EUR"   evidence: "Sous-total HT: 1.000,00 EUR"
  [Enter] accept · type correct value · [s] skip · [o] open page image
```

- Enter → `user_confirmed`. Typed value → type-checked (re-prompt on failure) → `user_corrected`. `s` → field stays failed; document `complete: false`. `o` → writes the page PNG to a temp file and opens it with `open`.
- Exit code: 0 if `complete`, 2 if any required field was skipped, 1 on errors.

## 6. Output

```json
{
  "complete": true,
  "fields": {
    "invoice_total": {"value": 1200.0, "raw": "1.200,00 EUR", "status": "valid",
                      "score": 0.95, "scores": {"shown": 0.97, "semantic": 0.95}, "page": 1}
  },
  "meta": {"extractor": "ollama:gemma4:31b-cloud", "validator": "clef-flash:9b", "threshold": 0.5}
}
```

## 7. Error handling

- **Ollama/clef-flash unreachable:** health check at startup; fail before any extractor request.
- **Extractor errors:** Ollama unreachable, non-200 (e.g. 402 "not in the Free plan"), or unparseable JSON → stop with a clear message.
- **Encrypted / corrupt / oversized PDF:** rejected up front with a message.
- **Scanned PDF:** works via full-page images; expect more review prompts.

## 8. Testing & calibration

### 8.1 Tests

1. **Unit (pytest, no models):** schema loading + JSON-schema generation + normalization; `pdf.locate` page/bbox correctness and crop geometry; text-layer detection; gate rules table; `review_cli` with scripted input (accept / correct / invalid correction / skip). clef and Ollama clients are faked.
2. **Integration (`@pytest.mark.clef`, skipped if Ollama is down):** generated sparse and dense pages; assert right value > 0.8, wrong value < 0.2, subtotal-as-total < 0.2 (regression guards; the pass mark is the threshold).
3. **End-to-end (`@pytest.mark.e2e`, needs Ollama signed in for the cloud extractor):** 2–3 known-answer PDFs through the full pipeline → `complete`, correct values, no prompts.

### 8.2 Calibration

- `eval/`: ~10 generated PDFs (invoice, receipt, form; FR and US formats; digital and image-only) with ground-truth JSON.
- `eval/calibrate.py` (no extractor calls): for each field, ask clef-flash about the true value and 3–4 adversarial wrong values (subtotal-as-total, transposed digits, wrong date, neighbouring field's value). Report false-accept and false-flag rates for thresholds 0.1–0.9 and recommend one.
- **Target:** 0 false accepts on the set, < 10% false flags.

## 9. Project layout

```
clef_pdf_extractor/
  pyproject.toml            # uv; deps: pymupdf, httpx, python-dateutil; dev: pytest
  src/clef_extractor/
    __init__.py  cli.py  schema.py  pdf.py  clef.py  validator.py  gate.py  review_cli.py
    extractors/  __init__.py  base.py  ollama.py  openai.py (commented out)
  tests/
  eval/  calibrate.py  make_samples.py  samples/
  docs/superpowers/specs/
```

## 10. Open risks

- clef-flash accuracy on real-world (non-synthetic) scans and handwriting is unmeasured; calibration set should be extended with real PDFs when available.
- The extractor may paraphrase `quote`; mitigated by the not-located fallback, but increases review prompts. Monitor the located rate.
