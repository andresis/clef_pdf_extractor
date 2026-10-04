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


def test_page_text():
    doc = Document(build_pdf(TWO_PAGES))
    assert "Total TTC: 1.200,00 EUR" in doc.page_text(2)
    assert "Total" not in doc.page_text(1)


def test_pymupdf_errors_mid_run_become_pdf_error(monkeypatch):
    doc = Document(build_pdf(INVOICE))

    class BrokenPage:
        def get_text(self):
            raise RuntimeError("damaged content stream")

        def get_pixmap(self, **kw):
            raise RuntimeError("damaged content stream")

        def search_for(self, needle):
            raise RuntimeError("damaged content stream")

    monkeypatch.setattr(doc, "_page", lambda page: BrokenPage())
    for call in (lambda: doc.page_text(1), lambda: doc.render_page(1), lambda: doc.locate("Total")):
        with pytest.raises(PdfError, match="damaged"):
            call()
