"""PDF access: validation, locating evidence text, rendering pages and crops to PNG."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pymupdf

MAX_BYTES = 50 * 1024 * 1024
CROP_MARGIN = 150.0


class PdfError(Exception):
    """The PDF can't be used."""


@dataclass(frozen=True)
class Location:
    page: int  # 1-based
    bbox: tuple[float, float, float, float]


class Document:
    def __init__(self, data: bytes, name: str = "document.pdf"):
        if len(data) > MAX_BYTES:
            raise PdfError(f"{name} is {len(data) / 1e6:.1f} MB; the limit is {MAX_BYTES // (1024 * 1024)} MB")
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as e:  # pymupdf raises several types for corrupt input
            raise PdfError(f"{name} is not a readable PDF: {e}") from e
        if doc.needs_pass:
            raise PdfError(f"{name} is encrypted")
        if doc.page_count == 0:
            raise PdfError(f"{name} has no pages")
        self.data = data
        self.name = name
        self._doc = doc

    @classmethod
    def from_path(cls, path: str | Path) -> "Document":
        p = Path(path)
        try:
            data = p.read_bytes()
        except OSError as e:
            raise PdfError(f"cannot read {p}: {e}") from e
        return cls(data, p.name)

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def valid_page(self, page: object) -> bool:
        return isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= self.page_count

    def has_text(self, page: int) -> bool:
        return bool(self.page_text(page).strip())

    def page_text(self, page: int) -> str:
        with self._guard(f"read text of page {page}"):
            return self._page(page).get_text()

    def locate(self, needle: str | None, hint_page: int | None = None) -> Location | None:
        """Find needle (whitespace-normalized) on the hint page first, then every other page."""
        needle = " ".join((needle or "").split())
        if not needle:
            return None
        order = list(range(1, self.page_count + 1))
        if self.valid_page(hint_page):
            order.remove(hint_page)
            order.insert(0, hint_page)
        for page in order:
            with self._guard(f"search page {page}"):
                hits = self._page(page).search_for(needle)
            if hits:
                r = hits[0]
                return Location(page, (r.x0, r.y0, r.x1, r.y1))
        return None

    def render_page(self, page: int, dpi: int = 100) -> bytes:
        with self._guard(f"render page {page}"):
            return self._page(page).get_pixmap(dpi=dpi).tobytes("png")

    def render_crop(self, page: int, bbox: tuple[float, float, float, float],
                    dpi: int = 150, margin: float = CROP_MARGIN) -> bytes:
        """Full page width, bbox ± margin points vertically."""
        with self._guard(f"render page {page}"):
            pg = self._page(page)
            r = pg.rect
            clip = pymupdf.Rect(r.x0, max(r.y0, bbox[1] - margin), r.x1, min(r.y1, bbox[3] + margin))
            return pg.get_pixmap(dpi=dpi, clip=clip).tobytes("png")

    @contextmanager
    def _guard(self, action: str):
        """Turn pymupdf failures on damaged pages into PdfError."""
        try:
            yield
        except PdfError:
            raise
        except Exception as e:
            raise PdfError(f"{self.name}: cannot {action}: {e}") from e

    def _page(self, page: int):
        if not self.valid_page(page):
            raise PdfError(f"page {page} out of range 1..{self.page_count}")
        return self._doc[page - 1]
