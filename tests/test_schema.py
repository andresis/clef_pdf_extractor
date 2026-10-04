import json

import pytest

from clef_extractor.schema import (
    Field,
    SchemaError,
    extraction_json_schema,
    load_fields,
    normalize,
    parse_fields,
)


def test_parse_fields_defaults_and_order():
    fields = parse_fields({
        "total": {"type": "number", "description": "Grand total", "required": True},
        "note": {"description": "Free text"},
    })
    assert fields == [
        Field("total", "number", "Grand total", True),
        Field("note", "string", "Free text", False),
    ]


@pytest.mark.parametrize("data, msg", [
    ({}, "non-empty"),
    ([], "non-empty"),
    ({"bad name": {"description": "x"}}, "invalid field name"),
    ({"x": {"type": "money", "description": "x"}}, "type must be"),
    ({"x": {"type": "string"}}, "description is required"),
    ({"x": {"description": "x", "required": "yes"}}, "required must be"),
    ({"x": "string"}, "must be an object"),
])
def test_parse_fields_rejects_invalid(data, msg):
    with pytest.raises(SchemaError, match=msg):
        parse_fields(data)


def test_load_fields_reads_file(tmp_path):
    p = tmp_path / "fields.json"
    p.write_text(json.dumps({"d": {"type": "date", "description": "Date"}}))
    assert load_fields(p) == [Field("d", "date", "Date", False)]


def test_load_fields_bad_json(tmp_path):
    p = tmp_path / "fields.json"
    p.write_text("{nope")
    with pytest.raises(SchemaError, match="cannot read"):
        load_fields(p)


def test_extraction_schema_is_strict():
    s = extraction_json_schema([Field("total", "number", "Grand total", True)])
    assert s["type"] == "object"
    assert s["additionalProperties"] is False
    assert s["required"] == ["total"]
    t = s["properties"]["total"]
    assert t["additionalProperties"] is False
    assert t["required"] == ["raw", "page", "quote"]
    assert t["properties"]["raw"]["type"] == ["string", "null"]
    assert t["properties"]["page"]["type"] == ["integer", "null"]
    assert t["properties"]["quote"]["type"] == ["string", "null"]
    assert "Grand total" in t["description"]


@pytest.mark.parametrize("raw, expected", [
    ("1.200,00 EUR", 1200.0),
    ("$2,652.13", 2652.13),
    ("1 200,50 €", 1200.5),
    ("1 200,50", 1200.5),
    ("12.45", 12.45),
    ("1,5", 1.5),
    ("1.200", 1200.0),
    ("1,200", 1200.0),
    ("0.125", 0.125),
    ("1.234.567,89", 1234567.89),
    ("1,234,567", 1234567.0),
    ("-42,10", -42.10),
    ("(15.00)", -15.0),
    ("200", 200.0),
])
def test_normalize_number(raw, expected):
    assert normalize("number", raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["abc", "", "1.2.3", "EUR"])
def test_normalize_number_rejects(raw):
    with pytest.raises(ValueError):
        normalize("number", raw)


@pytest.mark.parametrize("raw, expected", [
    ("03/10/2026", "2026-10-03"),
    ("2026-10-03", "2026-10-03"),
    ("03.10.2026", "2026-10-03"),
    ("10/25/2026", "2026-10-25"),
    ("October 3, 2026", "2026-10-03"),
    ("3 octobre 2026", "2026-10-03"),
    ("14 février 1990", "1990-02-14"),
    ("03/10/26", "2026-10-03"),
    ("2026-09-28 08:14", "2026-09-28"),
])
def test_normalize_date(raw, expected):
    assert normalize("date", raw) == expected


@pytest.mark.parametrize("raw", ["", "soon", "5", "13", "October 2026", "10/2026"])
def test_normalize_date_rejects(raw):  # incomplete dates must not get today's day/month filled in
    with pytest.raises(ValueError):
        normalize("date", raw)


def test_normalize_string():
    assert normalize("string", "  ACME SARL ") == "ACME SARL"
    with pytest.raises(ValueError):
        normalize("string", "   ")
