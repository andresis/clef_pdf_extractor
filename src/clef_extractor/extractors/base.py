"""The extractor interface shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..pdf import Document
from ..schema import Field


@dataclass(frozen=True)
class Candidate:
    name: str
    raw: str | None  # value exactly as printed, None if not found
    page: int | None  # 1-based page the extractor claims; verified later
    quote: str | None  # verbatim evidence snippet; verified later


class ExtractionError(Exception):
    """The extractor failed to produce candidates."""


class Extractor(Protocol):
    name: str

    def extract(self, doc: Document, fields: list[Field]) -> dict[str, Candidate]: ...


INSTRUCTIONS = """You extract field values from PDF documents. For each requested field return:
- raw: the value exactly as printed (keep currency symbols, separators and date format), or null if the document does not contain it. Never guess, compute or reformat values.
- page: the 1-based page number where the value is printed.
- quote: a short verbatim snippet copied from a single line of the document that contains the value, such as its label and the value (at most about 100 characters)."""


def fields_prompt(fields: list[Field]) -> str:
    lines = [f"- {f.name} ({f.type}{', required' if f.required else ''}): {f.description}" for f in fields]
    return "Fields to extract:\n" + "\n".join(lines)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def to_candidate(name: str, item: object) -> Candidate:
    """Build a Candidate from one field's JSON, discarding anything malformed."""
    if not isinstance(item, dict):
        return Candidate(name, None, None, None)
    page = item.get("page")
    page = page if isinstance(page, int) and not isinstance(page, bool) else None
    return Candidate(name, _text(item.get("raw")), page, _text(item.get("quote")))
