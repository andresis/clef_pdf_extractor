from clef_extractor.gate import Decision, apply_gate
from clef_extractor.schema import Field
from clef_extractor.validator import FieldResult


def result(required=True, raw="x", score=0.9):
    return FieldResult(Field("f", "string", "desc", required), raw=raw, value=raw, page=1, quote=None, score=score)


class Scripted:
    def __init__(self, decision):
        self.decision, self.seen = decision, []

    def __call__(self, r):
        self.seen.append(r)
        return self.decision


def test_passing_field_is_valid_and_not_reviewed():
    r, reviewer = result(score=0.9), Scripted(Decision("skip"))
    assert apply_gate([r], 0.5, reviewer) is True
    assert r.status == "valid" and reviewer.seen == []


def test_threshold_is_inclusive():
    r = result(score=0.5)
    apply_gate([r], 0.5, Scripted(Decision("skip")))
    assert r.status == "valid"


def test_optional_failures_are_not_reviewed():
    low, absent, reviewer = result(False, score=0.1), result(False, raw=None, score=0.0), Scripted(Decision("skip"))
    assert apply_gate([low, absent], 0.5, reviewer) is True
    assert low.status == "needs_review" and absent.status == "missing"
    assert reviewer.seen == []


def test_required_low_score_accepted():
    r = result(score=0.1)
    assert apply_gate([r], 0.5, Scripted(Decision("accept"))) is True
    assert r.status == "user_confirmed"


def test_required_corrected():
    r = result(score=0.1)
    assert apply_gate([r], 0.5, Scripted(Decision("correct", raw="New", value="New"))) is True
    assert r.status == "user_corrected" and r.raw == "New" and r.value == "New"


def test_required_skipped_makes_incomplete():
    low, absent = result(score=0.1), result(raw=None, score=0.0)
    assert apply_gate([low, absent], 0.5, Scripted(Decision("skip"))) is False
    assert low.status == "needs_review" and absent.status == "missing"
