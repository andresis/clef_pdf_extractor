"""Ollama backend (default: gemma4:31b-cloud). Sends page text, plus page images for vision models."""

from __future__ import annotations

import base64
import json
import re

import httpx

from ..pdf import Document
from ..schema import Field, extraction_json_schema
from .base import INSTRUCTIONS, Candidate, ExtractionError, fields_prompt, to_candidate

DEFAULT_MODEL = "gemma4:31b-cloud"
MAX_IMAGE_PAGES = 20  # above this, only pages without a text layer are sent as images
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse(content: str) -> dict:
    """Accept {name: {...}} or [{"field": name, ...}], optionally inside a ``` fence."""
    fenced = _FENCE.search(content or "")
    try:
        data = json.loads(fenced.group(1) if fenced else content)
    except (TypeError, json.JSONDecodeError) as e:
        raise ExtractionError("model did not return valid JSON") from e
    if isinstance(data, list):
        data = {d["field"]: d for d in data if isinstance(d, dict) and isinstance(d.get("field"), str)}
    if not isinstance(data, dict):
        raise ExtractionError("model did not return a JSON object")
    return data


class OllamaExtractor:
    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = "http://localhost:11434",
                 timeout: float = 300.0, transport: httpx.BaseTransport | None = None):
        self.model = model
        self.name = f"ollama:{model}"
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def has_vision(self) -> bool:
        return "vision" in self._post("/api/show", {"model": self.model}).get("capabilities", [])

    def extract(self, doc: Document, fields: list[Field]) -> dict[str, Candidate]:
        pages = []
        for p in range(1, doc.page_count + 1):
            text = doc.page_text(p).strip() or "(no text layer — see page image)"
            pages.append(f"=== Page {p} ===\n{text}")
        user: dict = {"role": "user", "content": "\n\n".join(pages) + "\n\n" + fields_prompt(fields)}
        if self.has_vision():
            image_pages = range(1, doc.page_count + 1)
            if doc.page_count > MAX_IMAGE_PAGES:
                image_pages = [p for p in image_pages if not doc.has_text(p)]
            user["images"] = [base64.b64encode(doc.render_page(p)).decode() for p in image_pages]
        reply = self._post("/api/chat", {
            "model": self.model,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
            "format": extraction_json_schema(fields),
            "messages": [{"role": "system", "content": INSTRUCTIONS}, user],
        })
        message = reply.get("message")
        data = _parse(message.get("content", "") if isinstance(message, dict) else "")
        return {f.name: to_candidate(f.name, data.get(f.name)) for f in fields}

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = self._http.post(path, json=body)
        except httpx.HTTPError as e:
            raise ExtractionError(f"Ollama request failed: {e}") from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if r.status_code != 200:
            raise ExtractionError(f"Ollama error ({r.status_code}) for {self.model}: {data.get('error', r.text)}")
        return data
