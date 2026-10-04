"""Generate the calibration set: synthetic PDFs + ground truth with adversarial wrong values.

Usage: uv run python eval/make_samples.py [--out eval/samples]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from clef_extractor._pdfgen import build_pdf


def f(type_, description, raw, wrong, page=1, required=True):
    return {"type": type_, "description": description, "required": required,
            "raw": raw, "page": page, "wrong": wrong}


FR_INVOICE = [[
    ("ACME SARL - FACTURE N° 2026-1042", 16), ("Date: 03/10/2026", 11), ("Client: Dupont SAS", 11), ("", 11),
    ("Sous-total HT: 1.000,00 EUR", 11, 300), ("TVA 20%: 200,00 EUR", 11, 300), ("Total TTC: 1.200,00 EUR", 11, 300),
]]
FR_INVOICE_FIELDS = {
    "invoice_number": f("string", "Invoice number", "2026-1042", ["2026-1024", "2025-1042"]),
    "invoice_date": f("date", "Invoice issue date", "03/10/2026", ["10/03/2026", "03/10/2025"]),
    "total": f("number", "Grand total including tax (TTC)", "1.200,00 EUR", ["1.000,00 EUR", "200,00 EUR", "1.020,00 EUR"]),
    "customer_name": f("string", "Name of the customer being billed", "Dupont SAS", ["ACME SARL"]),
}

FR_DENSE = [[("ACME SARL - FACTURE N° 2026-2077", 16), ("Date: 15/09/2026", 11)]
            + [(f"Ligne {i + 1:02d}  Article ref-{1000 + i}  Qte {i % 7 + 1}  PU {12.5 + i:.2f} EUR  "
                f"Total {(i % 7 + 1) * (12.5 + i):.2f} EUR", 7) for i in range(40)]
            + [("Sous-total HT: 4.310,50 EUR", 8, 300), ("TVA 20%: 862,10 EUR", 8, 300),
               ("Total TTC: 5.172,60 EUR", 8, 300)]]
FR_DENSE_FIELDS = {
    "invoice_date": f("date", "Invoice issue date", "15/09/2026", ["09/15/2025", "15/09/2025"]),
    "total": f("number", "Grand total including tax (TTC)", "5.172,60 EUR", ["4.310,50 EUR", "862,10 EUR", "5.127,60 EUR"]),
    "vat_amount": f("number", "VAT amount (TVA)", "862,10 EUR", ["5.172,60 EUR", "826,10 EUR"]),
}

US_INVOICE = [[
    ("Globex Inc. - INVOICE #INV-7781", 16), ("Invoice date: October 3, 2026", 11),
    ("Due date: November 2, 2026", 11), ("Bill to: Initech LLC", 11), ("", 11),
    ("Subtotal: $2,450.00", 11, 300), ("Sales tax (8.25%): $202.13", 11, 300), ("Total due: $2,652.13", 11, 300),
]]
US_INVOICE_FIELDS = {
    "invoice_number": f("string", "Invoice number", "INV-7781", ["INV-7718"]),
    "due_date": f("date", "Payment due date", "November 2, 2026", ["October 3, 2026", "November 20, 2026"]),
    "total": f("number", "Total amount due including tax", "$2,652.13", ["$2,450.00", "$202.13", "$2,625.13"]),
    "customer_name": f("string", "Name of the customer being billed", "Initech LLC", ["Globex Inc."]),
}

US_RECEIPT = [[
    ("CORNER CAFE", 16), ("Receipt 0042", 11), ("2026-09-28 08:14", 11), ("", 11),
    ("Latte 4.50", 11), ("Croissant 3.25", 11), ("Orange juice 3.75", 11), ("", 11),
    ("Subtotal 11.50", 11, 300), ("Tax 0.95", 11, 300), ("TOTAL 12.45", 11, 300), ("Paid VISA ****4242", 11),
]]
US_RECEIPT_FIELDS = {
    "date": f("date", "Purchase date", "2026-09-28", ["2026-09-29", "2026-08-28"]),
    "total": f("number", "Total paid", "12.45", ["11.50", "0.95", "12.54"]),
    "card_last4": f("string", "Last 4 digits of the payment card", "4242", ["4224", "0042"]),
}

FR_FORM = [[
    ("FORMULAIRE D'INSCRIPTION", 16), ("Nom: Martin", 11), ("Prénom: Claire", 11),
    ("Date de naissance: 14/02/1990", 11), ("Ville: Lyon", 11), ("Code postal: 69003", 11),
]]
FR_FORM_FIELDS = {
    "last_name": f("string", "Family name (nom)", "Martin", ["Claire"]),
    "birth_date": f("date", "Date of birth", "14/02/1990", ["14/02/1991", "12/04/1990"]),
    "postal_code": f("string", "Postal code", "69003", ["69300", "69030"]),
}

TWO_PAGE = [
    [("Initech LLC - INVOICE #A-501", 16), ("Date: 2026-08-01", 11)]
    + [(f"Item {i + 1:02d}  consulting hours  {i + 2} h  $150.00", 9) for i in range(30)],
    [("Subtotal: $9,900.00", 11, 300), ("Tax: $0.00", 11, 300), ("Total: $9,900.00", 11, 300)],
]
TWO_PAGE_FIELDS = {
    "invoice_date": f("date", "Invoice issue date", "2026-08-01", ["2026-01-08"]),
    "total": f("number", "Grand total", "$9,900.00", ["$9,090.00", "$150.00"], page=2),
}

SAMPLES = [
    ("fr_invoice_sparse", FR_INVOICE, FR_INVOICE_FIELDS, False),
    ("fr_invoice_dense", FR_DENSE, FR_DENSE_FIELDS, False),
    ("us_invoice", US_INVOICE, US_INVOICE_FIELDS, False),
    ("us_receipt", US_RECEIPT, US_RECEIPT_FIELDS, False),
    ("fr_form", FR_FORM, FR_FORM_FIELDS, False),
    ("two_page_invoice", TWO_PAGE, TWO_PAGE_FIELDS, False),
    ("fr_invoice_scanned", FR_INVOICE, FR_INVOICE_FIELDS, True),
    ("us_receipt_scanned", US_RECEIPT, US_RECEIPT_FIELDS, True),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent / "samples"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    for name, pages, fields, image_only in SAMPLES:
        (out / f"{name}.pdf").write_bytes(build_pdf(pages, image_only=image_only))
        (out / f"{name}.truth.json").write_text(
            json.dumps({"pdf": f"{name}.pdf", "fields": fields}, indent=2, ensure_ascii=False))
        defs = {k: {"type": v["type"], "description": v["description"], "required": v["required"]}
                for k, v in fields.items()}
        (out / f"{name}.fields.json").write_text(json.dumps(defs, indent=2, ensure_ascii=False))
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
