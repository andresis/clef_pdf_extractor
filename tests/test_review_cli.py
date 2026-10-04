import io

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
