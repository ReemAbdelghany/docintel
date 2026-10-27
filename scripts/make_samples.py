"""Generate the sample contract and an image of the sample invoice (into assets/Examples)."""

from pathlib import Path

import pypdfium2
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[1] / "assets" / "Examples"

CONTRACT = [
    "SERVICES AGREEMENT",
    "",
    "This Services Agreement is made between Nile Supplies Co. (the Supplier) and",
    "Delta Retail LLC (the Customer), effective 1 October 2026.",
    "",
    "1. The Supplier will deliver office furniture and installation services.",
    "2. The total contract value is EGP 250,000.00, payable in two instalments.",
    "3. This Agreement ends on 30 September 2027 unless renewed in writing.",
    "4. This Agreement is governed by the laws of the Arab Republic of Egypt.",
    "",
    "Signed for the Supplier: ______________    Signed for the Customer: ______________",
]


def make_contract() -> None:
    pdf = canvas.Canvas(str(OUT / "contract_services_agreement.pdf"), pagesize=A4)
    y = 780
    for line in CONTRACT:
        pdf.setFont("Helvetica-Bold" if line.isupper() else "Helvetica", 12)
        pdf.drawString(60, y, line)
        y -= 22
    pdf.save()


def make_invoice_image() -> None:
    page = pypdfium2.PdfDocument(str(OUT / "invoice_clean.pdf"))[0]
    page.render(scale=2).to_pil().save(OUT / "invoice_clean.png")


if __name__ == "__main__":
    make_contract()
    make_invoice_image()
    print(f"written to {OUT}")
