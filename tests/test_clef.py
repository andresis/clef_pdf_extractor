import base64
import json

import httpx
import pytest

from clef_extractor.clef import ClefClient, ClefError


def client(handler):
    return ClefClient(transport=httpx.MockTransport(handler))


def answers(**probs):
    return {"answers": {k: {"type": "noul", "noul": v} for k, v in probs.items()}}


def test_ask_sends_noul_questions_and_images():
    seen = {}

    def handler(request):
        assert request.url.path == "/v1/systemone"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=answers(shown=0.9, semantic=0.8))

    scores = client(handler).ask("the state", {"shown": "Q1", "semantic": "Q2"}, [b"png-bytes"])
    assert scores == {"shown": 0.9, "semantic": 0.8}
    assert seen["model"] == "clef-flash:9b"
    assert seen["state"] == "the state"
    assert seen["questions"]["shown"] == {"type": "noul", "instructions": "Q1"}
    assert seen["images"] == [base64.b64encode(b"png-bytes").decode()]


def test_ask_omits_images_when_none():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=answers(q=0.5))

    client(handler).ask("s", {"q": "Q"})
    assert "images" not in seen


def test_ask_raises_on_error_payload():
    handler = lambda request: httpx.Response(400, json={"error": "criteria must contain 2–26 candidates"})
    with pytest.raises(ClefError, match="criteria must contain"):
        client(handler).ask("s", {"q": "Q"})


def test_ask_raises_on_missing_answer():
    handler = lambda request: httpx.Response(200, json={"answers": {}})
    with pytest.raises(ClefError, match="unexpected"):
        client(handler).ask("s", {"q": "Q"})


def test_ask_raises_when_unreachable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ClefError, match="request failed"):
        client(handler).ask("s", {"q": "Q"})


def test_health_ok():
    handler = lambda request: httpx.Response(200, json={"models": [{"name": "clef-flash:9b"}]})
    client(handler).health()


def test_health_model_missing():
    handler = lambda request: httpx.Response(200, json={"models": [{"name": "other:1b"}]})
    with pytest.raises(ClefError, match="ollama pull clef-flash:9b"):
        client(handler).health()


def test_health_unreachable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ClefError, match="not reachable"):
        client(handler).health()


@pytest.mark.clef
def test_live_smoke():
    c = ClefClient()
    try:
        c.health()
    except ClefError as e:
        pytest.skip(str(e))
    scores = c.ask(
        "Invoice #1042. Subtotal: $100.00. Tax: $21.00. Total: $121.00",
        {"right": "Is the total 121.00?", "wrong": "Is the total 112.00?"},
    )
    assert scores["right"] > 0.8 and scores["wrong"] < 0.1


def test_health_non_json_body_raises_clef_error():
    handler = lambda request: httpx.Response(200, text="<html>proxy</html>")
    with pytest.raises(ClefError, match="unexpected"):
        client(handler).health()


def test_ask_error_with_list_body_raises_clef_error():
    handler = lambda request: httpx.Response(500, json=["boom"])
    with pytest.raises(ClefError, match="500"):
        client(handler).ask("s", {"q": "Q"})
