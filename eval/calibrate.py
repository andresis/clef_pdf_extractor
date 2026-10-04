"""Score true and adversarial wrong values with clef-flash; report error rates per threshold.

Usage: uv run python eval/calibrate.py [--samples eval/samples] [--csv eval/results.csv]
No extractor calls: candidates come from the ground truth.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from clef_extractor.calibration import Trial, recommend, summarize
from clef_extractor.clef import ClefClient
from clef_extractor.extractors.base import Candidate
from clef_extractor.pdf import Document
from clef_extractor.schema import Field
from clef_extractor.validator import Validator


def collect(samples: Path, clef: ClefClient) -> list[Trial]:
    trials = []
    for truth_path in sorted(samples.glob("*.truth.json")):
        truth = json.loads(truth_path.read_text())
        sample = truth_path.name.removesuffix(".truth.json")
        doc = Document.from_path(samples / truth["pdf"])
        validator = Validator(clef, doc)
        for name, spec in truth["fields"].items():
            field = Field(name, spec["type"], spec["description"], spec["required"])
            for raw, truthful in [(spec["raw"], True)] + [(w, False) for w in spec["wrong"]]:
                # Quote = the raw value: a wrong value that is printed elsewhere (e.g. the subtotal)
                # gets located there, just as a real extractor's quote would be.
                r = validator.validate(field, Candidate(name, raw, spec["page"], raw))
                trials.append(Trial(sample, name, raw, truthful, r.score, r.located))
                print(f"{sample:22} {name:16} {'TRUE ' if truthful else 'wrong'} {raw:22} {r.score:.3f}")
    return trials


def main() -> None:
    here = Path(__file__).parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default=str(here / "samples"))
    ap.add_argument("--csv", default=str(here / "results.csv"))
    args = ap.parse_args()

    clef = ClefClient()
    clef.health()
    trials = collect(Path(args.samples), clef)

    with open(args.csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sample", "field", "raw", "truthful", "score", "located"])
        for t in trials:
            w.writerow([t.sample, t.field, t.raw, t.truthful, f"{t.score:.4f}", t.located])

    stats = summarize(trials)
    print("\nthreshold  false_accepts  false_flags")
    for s in stats:
        print(f"  {s.threshold:.1f}      {s.false_accepts:3}/{s.wrong_total} ({s.false_accept_rate:5.1%})"
              f"   {s.false_flags:3}/{s.true_total} ({s.false_flag_rate:5.1%})")
    best = recommend(stats)
    print(f"\nrecommended threshold: {best.threshold:.1f} "
          f"(false accepts {best.false_accept_rate:.1%}, false flags {best.false_flag_rate:.1%})")
    print("target: 0 false accepts, < 10% false flags")

    print("\nhighest-scoring wrong values:")
    for t in sorted((t for t in trials if not t.truthful), key=lambda t: -t.score)[:5]:
        print(f"  {t.score:.3f}  {t.sample}/{t.field} = {t.raw}")
    print("lowest-scoring true values:")
    for t in sorted((t for t in trials if t.truthful), key=lambda t: t.score)[:5]:
        print(f"  {t.score:.3f}  {t.sample}/{t.field} = {t.raw}")


if __name__ == "__main__":
    main()
