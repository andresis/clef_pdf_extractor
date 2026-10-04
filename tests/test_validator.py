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


SCANNED = Document(build_pdf([[("Total TTC: 1.200,00 EUR", 11)]], image_only=True))


def test_not_located_on_scanned_page_uses_full_page_from_extractor():
    clef = FakeClef()
    r = Validator(clef, SCANNED).validate(TOTAL, Candidate("total", "1.200,00 EUR", 1, "Total TTC: 1.200,00 EUR"))
    assert not r.located and r.page == 1
    assert r.score == 0.7
    assert len(clef.calls[0][2]) == 1


def test_value_absent_from_digital_text_scores_zero_without_clef():
    # Calibration: transposed digits (5.127,60 for 5.172,60) scored 0.92 with clef, yet are printed nowhere.
    clef = FakeClef(shown=0.95, semantic=0.95)
    r = Validator(clef, DOC).validate(TOTAL, Candidate("total", "1.020,00 EUR", 2, "Total TTC: 1.020,00 EUR"))
    assert not r.located and r.page == 2
    assert r.score == 0.0 and r.scores == {}
    assert clef.calls == []


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
