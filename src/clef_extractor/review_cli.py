"""Interactive terminal review of required fields that failed validation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import TextIO

from .gate import Decision
from .pdf import Document
from .schema import normalize
from .validator import FieldResult


def _system_open(path: str) -> None:
    subprocess.run(["open", path], check=False)


class CliReviewer:
    def __init__(self, doc: Document, input_fn: Callable[[], str] = input,
                 out: TextIO | None = None, opener: Callable[[str], None] | None = None):
        self.doc = doc
        self.input_fn = input_fn
        self.out = out or sys.stderr
        self.opener = opener or _system_open

    def __call__(self, r: FieldResult) -> Decision:
        self._header(r)
        while True:
            self.out.write("> ")
            self.out.flush()
            try:
                line = self.input_fn().strip()
            except EOFError:
                self._say("\n  (no input available — skipping)")
                return Decision("skip")
            if line == "":
                if r.raw is None:
                    self._say("  Nothing to accept — type the correct value or 's' to skip.")
                    continue
                if r.value is None:
                    self._say(f"  '{r.raw}' is not a valid {r.field.type} — type the correct value or 's' to skip.")
                    continue
                return Decision("accept")
            if line.lower() == "s":
                return Decision("skip")
            if line.lower() == "o":
                self._open_page(r)
                continue
            try:
                value = normalize(r.field.type, line)
            except ValueError:
                self._say(f"  Not a valid {r.field.type}: {line!r}. Try again.")
                continue
            return Decision("correct", raw=line, value=value)

    def _header(self, r: FieldResult) -> None:
        page = r.page if r.page is not None else "?"
        extracted = f'"{r.raw}"' if r.raw is not None else "(nothing found)"
        evidence = f'   evidence: "{r.quote}"' if r.quote else ""
        self._say(f"\n✗ {r.field.name} (required) — confidence {r.score:.2f}, page {page}")
        self._say(f"  {r.field.description}")
        self._say(f"  Extracted: {extracted}{evidence}")
        self._say("  [Enter] accept · type correct value · [s] skip · [o] open page image")

    def _open_page(self, r: FieldResult) -> None:
        page = r.page if self.doc.valid_page(r.page) else 1
        with tempfile.NamedTemporaryFile(prefix=f"{r.field.name}-p{page}-", suffix=".png", delete=False) as f:
            f.write(self.doc.render_page(page, dpi=150))
        self.opener(f.name)
        self._say(f"  opened page {page}: {f.name}")

    def _say(self, text: str) -> None:
        print(text, file=self.out)
