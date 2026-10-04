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

    def extract(self, doc, fields):
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
    monkeypatch.setattr(cli, "OllamaExtractor", lambda **kw: extractor)
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


def test_output_dir_missing_exits_1_before_extraction(monkeypatch, capsys, files, tmp_path):
    pdf, fields = files
    extractor = FakeExtractor(CANDS)
    setup(monkeypatch, FakeClef(0.95), extractor)
    assert cli.main([str(pdf), "--fields", str(fields), "-o", str(tmp_path / "nope" / "out.json")]) == 1
    assert extractor.called is False
    assert "output directory" in capsys.readouterr().err


def test_keyboard_interrupt_exits_130(monkeypatch, capsys, files):
    pdf, fields = files

    class Interrupting(FakeExtractor):
        def extract(self, doc, fields):
            raise KeyboardInterrupt

    setup(monkeypatch, FakeClef(0.95), Interrupting(CANDS))
    assert cli.main([str(pdf), "--fields", str(fields)]) == 130
    assert "interrupted" in capsys.readouterr().err


def test_pdf_error_mid_run_exits_1(monkeypatch, capsys, files):
    pdf, fields = files
    from clef_extractor.pdf import PdfError

    class Broken(FakeExtractor):
        def extract(self, doc, fields):
            raise PdfError("inv.pdf: cannot render page 1: damaged")

    setup(monkeypatch, FakeClef(0.95), Broken(CANDS))
    assert cli.main([str(pdf), "--fields", str(fields)]) == 1
    assert "damaged" in capsys.readouterr().err
