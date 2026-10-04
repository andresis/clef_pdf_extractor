import base64
import json

import httpx
import pytest

from clef_extractor._pdfgen import build_pdf
from clef_extractor.extractors.base import Candidate, ExtractionError
from clef_extractor.extractors.ollama import OllamaExtractor
from clef_extractor.pdf import Document
from clef_extractor.schema import Field, extraction_json_schema

FIELDS = [Field("total", "number", "Grand total", True), Field("customer", "string", "Customer name", False)]
DOC = Document(build_pdf([[("Total TTC: 1.200,00 EUR", 11)], []]), "inv.pdf")  # page 2 has no text
PAYLOAD = {
    "total": {"raw": "1.200,00 EUR", "page": 1, "quote": "Total TTC: 1.200,00 EUR"},
    "customer": {"raw": None, "page": None, "quote": None},
}


class FakeOllama:
    def __init__(self, content=None, capabilities=("completion", "vision"), status=200, error=None):
        self.content, self.capabilities, self.status, self.error = content, list(capabilities), status, error
        self.chat_body = None

    def __call__(self, request):
        if self.error:
            raise self.error
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": self.capabilities})
        self.chat_body = json.loads(request.content)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "This model is not in the Free plan"})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": self.content}})


def extractor(fake, **kw):
    return OllamaExtractor(transport=httpx.MockTransport(fake), **kw)


def test_request_shape_with_vision():
    fake = FakeOllama(json.dumps(PAYLOAD))
    extractor(fake).extract(DOC, FIELDS)
    body = fake.chat_body
    assert body["model"] == "gemma4:31b-cloud"
    assert body["stream"] is False and body["think"] is False
    assert body["options"] == {"temperature": 0}
    assert body["format"] == extraction_json_schema(FIELDS)
    system, user = body["messages"]
    assert system["role"] == "system" and "exactly as printed" in system["content"]
    assert "=== Page 1 ===" in user["content"] and "Total TTC: 1.200,00 EUR" in user["content"]
    assert "=== Page 2 ===\n(no text layer" in user["content"]
    assert "- total (number, required): Grand total" in user["content"]
    assert len(user["images"]) == 2
    assert base64.b64decode(user["images"][0]).startswith(b"\x89PNG")


def test_no_images_without_vision():
    fake = FakeOllama(json.dumps(PAYLOAD), capabilities=("completion",))
    extractor(fake).extract(DOC, FIELDS)
    assert "images" not in fake.chat_body["messages"][1]


def test_parses_object_form():
    result = extractor(FakeOllama(json.dumps(PAYLOAD))).extract(DOC, FIELDS)
    assert result == {
        "total": Candidate("total", "1.200,00 EUR", 1, "Total TTC: 1.200,00 EUR"),
        "customer": Candidate("customer", None, None, None),
    }


def test_parses_fenced_list_form():
    content = '```json\n[{"field": "total", "raw": "1.200,00 EUR", "page": 1, "quote": "Total TTC: 1.200,00 EUR"}]\n```'
    result = extractor(FakeOllama(content)).extract(DOC, FIELDS)
    assert result["total"] == Candidate("total", "1.200,00 EUR", 1, "Total TTC: 1.200,00 EUR")
    assert result["customer"] == Candidate("customer", None, None, None)


def test_missing_and_malformed_fields_become_empty_candidates():
    content = json.dumps({"total": {"raw": "  ", "page": True, "quote": 5}, "extra": {"raw": "x"}})
    result = extractor(FakeOllama(content)).extract(DOC, FIELDS)
    assert result == {
        "total": Candidate("total", None, None, None),
        "customer": Candidate("customer", None, None, None),
    }


def test_invalid_json_raises():
    with pytest.raises(ExtractionError, match="valid JSON"):
        extractor(FakeOllama("sorry, no idea")).extract(DOC, FIELDS)


def test_http_error_status_raises_with_message():
    with pytest.raises(ExtractionError, match="not in the Free plan"):
        extractor(FakeOllama(status=402)).extract(DOC, FIELDS)


def test_unreachable_raises():
    with pytest.raises(ExtractionError, match="request failed"):
        extractor(FakeOllama(error=httpx.ConnectError("refused"))).extract(DOC, FIELDS)


def test_name_reflects_model():
    assert OllamaExtractor(model="nemotron-3-super:cloud").name == "ollama:nemotron-3-super:cloud"


@pytest.mark.e2e
def test_live_gemma_digital_and_scanned():
    pages = [[("ACME SARL - FACTURE N° 2026-1042", 16), ("Date: 03/10/2026", 11),
              ("Sous-total HT: 1.000,00 EUR", 11, 300), ("Total TTC: 1.200,00 EUR", 11, 300)]]
    fields = [Field("total", "number", "Grand total including tax", True),
              Field("invoice_date", "date", "Invoice issue date", True)]
    for image_only in (False, True):
        result = OllamaExtractor().extract(Document(build_pdf(pages, image_only=image_only)), fields)
        assert result["total"].raw and "1.200,00" in result["total"].raw
        assert result["invoice_date"].raw == "03/10/2026"
