# clef-pdf-extractor — progress

Plan: docs/superpowers/plans/2026-10-03-clef-pdf-extractor.md

- [x] Task 1: Project scaffold + field schema
- [x] Task 2: PDF document (locate, render)
- [x] Task 3: clef-flash client
- [x] Task 4: Ollama cloud extractor (OpenAI commented out)
- [x] Task 5: Validator
- [x] Task 6: Gate + review CLI
- [x] Task 7: CLI wiring + README
- [x] Task 8: Calibration set + script

## Review

### Extractor probe (2026-10-04)
gemma4:31b-cloud extracted all fields of a dense FR invoice correctly, digital and scanned (scan: dropped "EUR").
It ignores the JSON-schema `format` and returns a fenced list — handled by lenient parsing.
glm-5.3:cloud and deepseek-v4.1-flash:cloud need Ollama Pro (HTTP 402).

### Calibration (eval/calibrate.py, 8 samples, 26 true / 52 wrong values)
| threshold | false accepts | false flags |
|---|---|---|
| 0.1–0.3 | 5/52 (9.6%) | 0/26 |
| 0.4 | 4/52 (7.7%) | 0/26 |
| 0.5–0.8 | 3/52 (5.8%) | 0/26 |
| 0.9 | 2/52 (3.8%) | 0/26 |

Target (0 false accepts, <10% false flags) **missed**. True values all score ≥ 0.937.
All false accepts at 0.5 are transposed digits that are NOT printed anywhere in the document:
`5.127,60 EUR` (true `5.172,60`) 0.924, `4224` (true `4242`) 0.906 digital / 0.861 scanned.
Default threshold left at 0.5 pending a decision.

### End-to-end (pytest -m e2e)
2/3 pass. us_invoice: gemma returned `#INV-7781` (printed "INVOICE #INV-7781"); clef accepted it
(the text is on the page), ground truth is `INV-7781`. Not weakened — needs a decision.

### Post-review (2026-10-04)
Review fixes applied: year-first dates, strict number shape, clean errors (-o, Ctrl-C, non-JSON replies,
damaged pages), page-image cap >20 pages.
Applied reviewer #8 (user decision): a value absent from the text layer of a digital page scores 0 without a clef call.
Calibration after: false accepts 1/52 at 0.5 (only us_receipt_scanned `4224`, 0.861 — scans rely on clef alone),
0/52 at 0.9; false flags 0/26 at every threshold. Default threshold still 0.5 (true values ≥ 0.937).
e2e: 3/4 pass; open: `#INV-7781` vs `INV-7781`.
