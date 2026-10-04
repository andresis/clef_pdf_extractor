"""OpenAI Responses API backend (GPT-6.1 Sol). DISABLED — see the note below."""

# To enable: `uv add openai`, uncomment this module, and select it in cli.py.
# Verified API shape (2026-10-03): Responses API, PDF as base64 `input_file`, strict json_schema
# via `text.format`, `reasoning.effort` low..max. Combination of input_file + json_schema is
# unconfirmed — run one real request before relying on it.
#
# import base64
# import json
#
# import openai
#
# from ..pdf import Document
# from ..schema import Field, extraction_json_schema
# from .base import INSTRUCTIONS, Candidate, ExtractionError, fields_prompt, to_candidate
#
# DEFAULT_MODEL = "gpt-6.1-sol"
#
#
# class OpenAIExtractor:
#     def __init__(self, model: str = DEFAULT_MODEL, effort: str = "low", client=None):
#         self.client = client if client is not None else openai.OpenAI()
#         self.model = model
#         self.effort = effort
#         self.name = f"openai:{model}"
#
#     def extract(self, doc: Document, fields: list[Field]) -> dict[str, Candidate]:
#         file_data = "data:application/pdf;base64," + base64.b64encode(doc.data).decode()
#         try:
#             resp = self.client.responses.create(
#                 model=self.model,
#                 reasoning={"effort": self.effort},
#                 instructions=INSTRUCTIONS,
#                 input=[{"role": "user", "content": [
#                     {"type": "input_file", "filename": doc.name, "file_data": file_data},
#                     {"type": "input_text", "text": fields_prompt(fields)},
#                 ]}],
#                 text={"format": {"type": "json_schema", "name": "extraction", "strict": True,
#                                  "schema": extraction_json_schema(fields)}},
#             )
#         except openai.OpenAIError as e:
#             raise ExtractionError(f"OpenAI request failed: {e}") from e
#
#         for item in getattr(resp, "output", None) or []:
#             for part in getattr(item, "content", None) or []:
#                 if getattr(part, "type", None) == "refusal":
#                     raise ExtractionError(f"model refused: {part.refusal}")
#         if resp.status != "completed":
#             reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
#             raise ExtractionError(f"OpenAI response {resp.status}" + (f": {reason}" if reason else ""))
#         try:
#             data = json.loads(resp.output_text)
#         except (TypeError, json.JSONDecodeError) as e:
#             raise ExtractionError("model did not return valid JSON") from e
#         if not isinstance(data, dict):
#             raise ExtractionError("model did not return a JSON object")
#         return {f.name: to_candidate(f.name, data.get(f.name)) for f in fields}
