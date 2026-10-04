"""Full pipeline against the Ollama cloud extractor + local clef-flash. Run with `-m e2e`."""

import json
from pathlib import Path

import pytest

from clef_extractor.cli import run
from clef_extractor.clef import ClefClient
from clef_extractor.extractors.ollama import OllamaExtractor
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

    result = run(doc, fields, OllamaExtractor(), Validator(clef, doc), reviewer, 0.5)
    assert asked == [], f"unexpected review prompts: {asked}"
    assert result["complete"] is True
    for field_name, spec in truth["fields"].items():
        assert result["fields"][field_name]["value"] == normalize(spec["type"], spec["raw"])
