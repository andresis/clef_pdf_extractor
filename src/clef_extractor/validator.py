"""Validate extracted candidates against the rendered PDF page with clef-flash."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from .extractors.base import Candidate
from .pdf import Document
from .schema import Field, normalize


@dataclass
class FieldResult:
    field: Field
    raw: str | None
    value: str | float | None
    page: int | None
    quote: str | None
    located: bool = False
    scores: dict[str, float] = dc_field(default_factory=dict)
    score: float = 0.0
    status: str = "pending"


def _state(field: Field, raw: str, page: int) -> str:
    return (f"Document page {page}. Field '{field.name}': {field.description}. "
            f"Extracted value as printed: '{raw}'.")


def _questions(field: Field, raw: str) -> dict[str, str]:
    return {
        "shown": f"Does the image show the value '{raw}'?",
        "semantic": (f"Is '{raw}' the correct value for '{field.description}' according to this document, "
                     f"and not some other value on the page?"),
    }


class Validator:
    def __init__(self, clef, doc: Document):
        self.clef = clef
        self.doc = doc

    def validate(self, field: Field, cand: Candidate) -> FieldResult:
        result = FieldResult(field, cand.raw, None, cand.page, cand.quote)
        if cand.raw is None:
            return result
        try:
            result.value = normalize(field.type, cand.raw)
            type_ok = True
        except ValueError:
            type_ok = False

        loc = self.doc.locate(cand.quote, cand.page) or self.doc.locate(cand.raw, cand.page)
        if loc:
            result.page, result.located = loc.page, True
            images = [self.doc.render_crop(loc.page, loc.bbox), self.doc.render_page(loc.page)]
        elif self.doc.valid_page(cand.page):
            images = [self.doc.render_page(cand.page)]
        else:
            result.page = None
            return result

        result.scores = self.clef.ask(_state(field, cand.raw, result.page), _questions(field, cand.raw), images)
        result.score = min(result.scores.values()) if type_ok else 0.0
        return result
