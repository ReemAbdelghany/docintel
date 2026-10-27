"""Generate synthetic invoice PDFs for demos and evals.

Run: uv run python scripts/make_sample_invoices.py

All data is invented. Never commit real customer documents.
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "assets" / "Examples"

LINES = [
    ("Office chairs (4)", "400.00"),
    ("Standing desk", "350.00"),
    ("Delivery and assembly", "250.00"),
]


def draw_invoice(path: Path, number: str, total: str) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(60, y, "Nile Supplies Co.")
    pdf.setFont("Helvetica", 11)
    for text in (
        "12 Tahrir Street, Cairo, Egypt",
        f"Invoice No: {number}",
        "Issue Date: 2026-09-30",
        "Bill To: Delta Trading LLC",
    ):
        y -= 22
        pdf.drawString(60, y, text)
    y -= 40
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(60, y, "Description")
    pdf.drawString(420, y, "Amount (EGP)")
    pdf.setFont("Helvetica", 11)
    for description, amount in LINES:
        y -= 22
        pdf.drawString(60, y, description)
        pdf.drawRightString(520, y, amount)
    y -= 40
    for label, value in (("Subtotal", "1000.00"), ("VAT 14%", "140.00"), ("Total", total)):
        pdf.drawString(360, y, label)
        pdf.drawRightString(520, y, f"EGP {value}")
        y -= 22
    pdf.save()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw_invoice(OUT / "invoice_clean.pdf", "INV-204", "1140.00")
    draw_invoice(OUT / "invoice_wrong_total.pdf", "INV-205", "1200.00")
    print(f"wrote {OUT}")
