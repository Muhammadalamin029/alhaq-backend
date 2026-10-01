"""Server-side vector receipt PDFs (fpdf2).

Renders the SAME receipt dicts consumed by `render_receipt_html`
(`core/receipt_service.build_receipt` and
`core/external_receipt_service.build_external_receipt_dict`) as native PDF
text/tables — no rasterisation, so alignment is exact by construction and
output stays sharp and selectable on every platform.

Design mirrors `core/templates/receipt.html` (accent bar, header, status
badge, items table, totals, payment details, footer) without pixel-copying
it: the PDF is the canonical download artifact going forward.
"""

from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from fpdf import FPDF
from fpdf.fonts import FontFace
from sqlalchemy.orm import Session

from core.model import ExternalPayment

_HERE = Path(__file__).resolve().parent
_FONTS = _HERE / "fonts"
_ASSETS = _HERE / "assets"

INK = (22, 24, 29)
MUTED = (107, 114, 128)
LINE = (230, 232, 235)
ORANGE_DEEP = (226, 98, 10)
GREEN = (26, 156, 83)
GREEN_SOFT = (224, 242, 232)
AMBER = (184, 121, 10)
AMBER_SOFT = (250, 238, 214)
RED = (209, 52, 47)
RED_SOFT = (250, 222, 221)


def _accent_for(status: str) -> tuple[tuple, tuple]:
    s = (status or "").lower()
    if s in ("paid", "success", "successful", "completed"):
        return GREEN, GREEN_SOFT
    if s in ("pending", "processing", "awaiting payment"):
        return AMBER, AMBER_SOFT
    return RED, RED_SOFT


def _money(value: Any) -> str:
    if value is None:
        return "NGN 0.00"
    return f"NGN {Decimal(value):,.2f}"


def _fmt_dt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M")
    return "-"


def _related_label(receipt: Dict[str, Any]) -> str:
    if receipt.get("show_related", True) is False:
        return ""
    order = receipt.get("order")
    if order:
        return f"Order #{str(order['id']).split('-')[0].upper()}"
    agreement = receipt.get("agreement")
    if agreement:
        return f"Agreement #{str(agreement['id']).split('-')[0].upper()}"
    return ""


def _new_pdf() -> FPDF:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(15, 12, 15)
    pdf.add_font("deja", "", str(_FONTS / "DejaVuSans.ttf"), uni=True)
    pdf.add_font("deja", "B", str(_FONTS / "DejaVuSans-Bold.ttf"), uni=True)
    return pdf


def _hr(pdf: FPDF) -> None:
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.3)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.set_y(y + 5)


def render_receipt_pdf(receipt: Dict[str, Any]) -> bytes:
    """Render a receipt dict (same shape as `render_receipt_html` takes)."""
    accent, accent_soft = _accent_for(receipt.get("status"))
    payer = receipt.get("payer") or {}
    payee = receipt.get("payee") or {}
    order = receipt.get("order")
    agreement = receipt.get("agreement")
    related = _related_label(receipt)

    pdf = _new_pdf()
    pdf.add_page()
    content_w = pdf.w - pdf.l_margin - pdf.r_margin

    # Top accent bar (full-bleed).
    pdf.set_fill_color(*accent)
    pdf.rect(0, 0, pdf.w, 2.5, style="F")
    pdf.set_y(12)

    # ---- Header ---------------------------------------------------------
    logo_path = _ASSETS / "logo.png"
    top = pdf.get_y()
    if logo_path.exists():
        pdf.image(str(logo_path), x=pdf.l_margin, y=top, w=9, h=9)
    pdf.set_xy(pdf.l_margin + 12, top + 0.5)
    pdf.set_font("deja", "B", 13)
    pdf.set_text_color(*INK)
    pdf.cell(0, 5, payee.get("name") or "LEL Store")
    pdf.set_xy(pdf.l_margin + 12, top + 5.5)
    pdf.set_font("deja", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 4, "Payment receipt")

    pdf.set_xy(pdf.l_margin, top)
    pdf.set_font("deja", "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(content_w, 5, receipt.get("receipt_number") or "", align="R")
    pdf.set_x(pdf.l_margin)
    pdf.set_font("deja", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(content_w, 4.5, f"Issued {_fmt_dt(receipt.get('issued_at'))}",
             align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(top + 15)
    _hr(pdf)

    # ---- Status line ----------------------------------------------------
    y0 = pdf.get_y()
    # Concentric badge: soft halo + solid core (pure geometry, no glyph).
    cx = pdf.l_margin + 6
    cy = y0 + 6
    pdf.set_fill_color(*accent_soft)
    pdf.ellipse(cx - 6, cy - 6, 12, 12, style="F")
    pdf.set_fill_color(*accent)
    pdf.ellipse(cx - 4.5, cy - 4.5, 9, 9, style="F")
    # Reset fill state: table cells paint their (unstyled) backgrounds with
    # whatever fill colour is current — without this they inherit badge green.
    pdf.set_fill_color(255, 255, 255)

    pdf.set_xy(pdf.l_margin + 16, y0)
    is_paid = accent == GREEN
    is_pending = accent == AMBER
    pdf.set_font("deja", "B", 13)
    pdf.set_text_color(*INK)
    title = ("Payment received" if is_paid
             else "Payment pending" if is_pending
             else f"Payment {receipt.get('status')}")
    pdf.cell(0, 6, title)
    pdf.set_xy(pdf.l_margin + 16, y0 + 6.5)
    pdf.set_font("deja", "", 10)
    # Mixed-colour greeting via inline HTML (small, well-supported subset).
    payer_name = escape(payer.get("name") or "there")
    payee_name = escape(payee.get("name") or "LEL Store")
    pdf.write_html(
        f'<font color="#6b7280">Hi </font>'
        f'<font color="#e2620a"><b>{payer_name}</b></font>'
        f'<font color="#6b7280"> \u00b7 paid to '
        f'{payee_name}</font>'
    )
    # Amount block (right).
    pdf.set_xy(pdf.l_margin, y0)
    pdf.set_font("deja", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(content_w, 4, "Amount", align="R")
    pdf.set_xy(pdf.l_margin, y0 + 5)
    pdf.set_font("deja", "B", 17)
    pdf.set_text_color(*accent)
    pdf.cell(content_w, 8, _money(receipt.get("amount")), align="R",
             new_x="LMARGIN", new_y="NEXT")
    # Reset graphics state: later draws must never inherit accent colour.
    pdf.set_text_color(*INK)
    pdf.set_fill_color(255, 255, 255)
    pdf.set_y(max(pdf.get_y(), y0 + 16) + 2)
    _hr(pdf)

    # ---- Items / agreement ----------------------------------------------
    if order:
        _items_table(pdf, content_w, order)
        _totals_block(pdf, content_w, order, accent)
    elif agreement:
        _kv_rows(pdf, content_w, [
            ("Asset", agreement.get("asset_name") or agreement.get("asset_type")),
            ("Payment plan",
             str(agreement.get("payment_plan") or "").replace("_", " ").title()),
            ("Agreement total", _money(agreement.get("total_price"))),
            ("Remaining balance", _money(agreement.get("remaining_balance"))),
        ])

    # ---- Payment details --------------------------------------------------
    pdf.set_font("deja", "B", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, "Payment details", new_x="LMARGIN", new_y="NEXT")
    rows = [("Purpose", receipt.get("purpose") or "Payment")]
    if related:
        rows.append(("Related", related))
    if receipt.get("reference"):
        rows.append(("Reference", receipt["reference"]))
    if receipt.get("transaction_id"):
        rows.append(("Transaction ID", receipt["transaction_id"]))
    if receipt.get("payment_method"):
        rows.append(("Payment method", receipt["payment_method"]))
    rows.append(("Date paid", _fmt_dt(receipt.get("paid_at"))))
    paid_by = payer.get("name") or "-"
    if payer.get("email"):
        paid_by += f" ({payer['email']})"
    rows.append(("Paid by", paid_by))
    _kv_rows(pdf, content_w, rows)

    # ---- Footer -----------------------------------------------------------
    pdf.ln(4)
    y = pdf.get_y()
    if y > pdf.h - 30:
        pdf.add_page()
        y = pdf.get_y()
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.set_y(y + 4)
    pdf.set_font("deja", "", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(content_w, 4.5,
                   "This receipt is an acknowledgement of payment received. "
                   "It is generated electronically and is valid without a signature.",
                   align="C")
    return bytes(pdf.output())


def _items_table(pdf: FPDF, content_w: float, order: Dict[str, Any]) -> None:
    items = order.get("items") or []
    pdf.set_text_color(*INK)
    pdf.set_fill_color(255, 255, 255)
    head = FontFace(emphasis="BOLD", color=MUTED)
    name_face = FontFace(emphasis="BOLD", color=INK)
    body = FontFace(color=INK)
    with pdf.table(
        col_widths=(44, 10, 23, 23),
        width=content_w,
        line_height=6.5,
        text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT"),
        borders_layout="HORIZONTAL_LINES",
        cell_fill_color=(255, 255, 255),
        padding=(1.5, 1.5, 1.5, 1.5),
    ) as table:
        hdr = table.row()
        hdr.cell("Item", style=head)
        hdr.cell("Qty", style=head)
        hdr.cell("Unit price", style=head)
        hdr.cell("Amount", style=head)
        for line in items:
            row = table.row()
            row.cell(str(line.get("name") or "Item"), style=name_face)
            row.cell(str(line.get("quantity") or 0), style=body)
            row.cell(_money(line.get("unit_price")), style=body)
            row.cell(_money(line.get("line_total")), style=body)
    pdf.ln(2)


def _totals_block(pdf: FPDF, content_w: float, order: Dict[str, Any],
                   accent) -> None:
    block_w = 80
    left = pdf.l_margin + content_w - block_w
    pdf.set_text_color(*INK)
    pdf.set_fill_color(255, 255, 255)
    pdf.set_font("deja", "", 10)

    def _row(label: str, value: str, bold=False, color=None, size=10):
        pdf.set_xy(left, pdf.get_y())
        pdf.set_text_color(*MUTED)
        pdf.set_font("deja", "B" if bold else "", size)
        pdf.cell(block_w * 0.42, 6, label)
        pdf.set_text_color(*(color or INK))
        pdf.set_font("deja", "B", size)
        pdf.cell(block_w * 0.58, 6, value, align="R",
                 new_x="LMARGIN", new_y="NEXT")

    _row("Subtotal", _money(order.get("subtotal")))
    if order.get("delivery_fee"):
        _row("Delivery fee", _money(order.get("delivery_fee")))
    y = pdf.get_y() + 1
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.3)
    pdf.line(left, y, left + block_w, y)
    pdf.set_y(y + 2)
    _row("Total", _money(order.get("total")), bold=True, color=accent, size=12)
    pdf.ln(4)


def _kv_rows(pdf: FPDF, content_w: float, rows: list) -> None:
    pdf.set_text_color(*INK)
    pdf.set_fill_color(255, 255, 255)
    label_face = FontFace(color=MUTED)
    value_face = FontFace(emphasis="BOLD", color=INK)
    with pdf.table(
        col_widths=(42, 58),
        width=content_w,
        line_height=6.5,
        text_align=("LEFT", "RIGHT"),
        borders_layout="HORIZONTAL_LINES",
        cell_fill_color=(255, 255, 255),
        padding=(1.5, 1.5, 1.5, 1.5),
    ) as table:
        for label, value in rows:
            row = table.row()
            row.cell(str(label), style=label_face)
            row.cell(str(value or "-"), style=value_face)
    pdf.ln(2)


def render_external_receipt_pdf(db: Session, payment_id: UUID) -> Optional[bytes]:
    """Vector PDF for an external payment, or None if not found."""
    from core.external_receipt_service import build_external_receipt_dict

    payment = (
        db.query(ExternalPayment).filter(ExternalPayment.id == payment_id).first()
    )
    if not payment:
        return None
    return render_receipt_pdf(build_external_receipt_dict(db, payment))
