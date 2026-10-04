"""Thin client for clef-flash's /v1/systemone endpoint on a local Ollama."""

from __future__ import annotations

import base64
from collections.abc import Sequence

import httpx


class ClefError(Exception):
    """clef-flash is unavailable or returned something unusable."""


class ClefClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "clef-flash:9b",
                 timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        self.model = model
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def health(self) -> None:
        try:
            r = self._http.get("/api/tags")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ClefError(f"Ollama not reachable at {self._http.base_url}: {e}") from e
        try:
            names = {m.get("name") for m in r.json().get("models", [])}
        except (ValueError, AttributeError) as e:
            raise ClefError(f"unexpected response from Ollama at {self._http.base_url}/api/tags") from e
        if self.model not in names:
            raise ClefError(f"model {self.model} is not installed; run: ollama pull {self.model}")

    def ask(self, state: str, questions: dict[str, str], images: Sequence[bytes] = ()) -> dict[str, float]:
        """Ask boolean (noul) questions; returns question key → probability of 'yes'."""
        body: dict = {
            "model": self.model,
            "state": state,
            "questions": {k: {"type": "noul", "instructions": v} for k, v in questions.items()},
        }
        if images:
            body["images"] = [base64.b64encode(img).decode() for img in images]
        try:
            r = self._http.post("/v1/systemone", json=body)
        except httpx.HTTPError as e:
            raise ClefError(f"clef-flash request failed: {e}") from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if r.status_code != 200:
            raise ClefError(f"clef-flash error ({r.status_code}): {data.get('error', r.text)}")
        try:
            return {k: float(data["answers"][k]["noul"]) for k in questions}
        except (KeyError, TypeError, ValueError) as e:
            raise ClefError(f"unexpected clef-flash response: {data}") from e
