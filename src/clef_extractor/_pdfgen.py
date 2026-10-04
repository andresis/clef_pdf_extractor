"""Build simple synthetic PDFs for tests and the calibration set."""

from __future__ import annotations

import pymupdf


def build_pdf(pages: list[list[tuple]], image_only: bool = False, dpi: int = 150) -> bytes:
    """Each page is a list of lines: (text, fontsize) or (text, fontsize, x).

    image_only=True rasterizes every page, producing a PDF with no text layer (a "scan").
    """
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 60.0
        for line in lines:
            text, size = line[0], line[1]
            x = line[2] if len(line) > 2 else 50.0
            if text:
                page.insert_text((x, y), text, fontsize=size)
            y += size * 1.6
    if image_only:
        scanned = pymupdf.open()
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            new_page = scanned.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, pixmap=pix)
        doc = scanned
    return doc.tobytes()
