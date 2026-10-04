"""Command line entry point: extract → validate → gate → JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .clef import ClefClient, ClefError
from .extractors.base import ExtractionError
from .extractors.ollama import DEFAULT_MODEL, OllamaExtractor
from .gate import apply_gate
from .pdf import Document, PdfError
from .review_cli import CliReviewer
from .schema import Field, SchemaError, load_fields
from .validator import Validator


def run(doc: Document, fields: list[Field], extractor, validator: Validator, reviewer, threshold: float) -> dict:
    candidates = extractor.extract(doc, fields)
    results = [validator.validate(f, candidates[f.name]) for f in fields]
    complete = apply_gate(results, threshold, reviewer)
    return {
        "file": doc.name,
        "complete": complete,
        "fields": {
            r.field.name: {
                "value": r.value,
                "raw": r.raw,
                "status": r.status,
                "score": round(r.score, 4),
                "scores": {k: round(v, 4) for k, v in r.scores.items()},
                "page": r.page,
            }
            for r in results
        },
        "meta": {"extractor": extractor.name, "validator": validator.clef.model, "threshold": threshold},
    }


def _threshold(text: str) -> float:
    value = float(text)
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError("threshold must be between 0 and 1")
    return value


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="clef-extract", description=__doc__)
    p.add_argument("pdf", help="PDF file to extract from")
    p.add_argument("--fields", required=True, help="JSON file defining the fields to extract")
    p.add_argument("--threshold", type=_threshold, default=0.5, help="minimum clef-flash score to accept (0-1)")
    p.add_argument("-o", "--output", help="write result JSON here instead of stdout")
    p.add_argument("--model", default=os.environ.get("EXTRACT_MODEL", DEFAULT_MODEL),
                   help="Ollama model used for extraction")
    p.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama base URL")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.output and not Path(args.output).resolve().parent.is_dir():
        print(f"error: output directory does not exist: {Path(args.output).parent}", file=sys.stderr)
        return 1
    try:
        fields = load_fields(args.fields)
        doc = Document.from_path(args.pdf)
        extractor = OllamaExtractor(model=args.model, base_url=args.ollama_url)
        clef = ClefClient(base_url=args.ollama_url)
        clef.health()  # before any extractor request
        result = run(doc, fields, extractor, Validator(clef, doc), CliReviewer(doc), args.threshold)
    except (SchemaError, PdfError, ClefError, ExtractionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        try:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        except OSError as e:
            print(text)  # don't lose the reviewed result
            print(f"error: cannot write {args.output}: {e}", file=sys.stderr)
            return 1
    else:
        print(text)
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
