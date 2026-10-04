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
    # Probe 2026-10-03 (this exact request): right 0.96, wrong 0.017–0.06, subtotal 0.013–0.046.
    assert score("1.500,00 EUR", None) < 0.2
    assert score("1.000,00 EUR", "Sous-total HT: 1.000,00 EUR") < 0.2
