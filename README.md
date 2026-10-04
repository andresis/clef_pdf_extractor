# clef-pdf-extractor

Extract fields from any PDF with an Ollama cloud model (default `gemma4:31b-cloud`), validate every value locally with
[clef-flash](https://ollama.com/library/clef-flash), and get asked about any required field that fails.

## Setup

```bash
ollama pull clef-flash:9b      # local validator
ollama signin                  # cloud extractor (gemma4:31b-cloud works on the free plan)
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

Options: `--threshold 0.5` (minimum clef-flash score), `--model gemma4:31b-cloud` (or `EXTRACT_MODEL`; any Ollama model),
`--ollama-url http://localhost:11434`.

When a required field fails, you're prompted: Enter accepts, typing replaces the value, `s` skips, `o` opens the page.
Exit codes: 0 complete, 2 a required field was skipped, 1 error.

## Tests

```bash
uv run pytest               # unit tests, no network
uv run pytest -m clef       # needs Ollama with clef-flash:9b
uv run pytest -m e2e        # needs Ollama signed in (cloud extractor) + clef-flash
```

## Calibration

```bash
uv run python eval/make_samples.py
uv run python eval/calibrate.py
```
