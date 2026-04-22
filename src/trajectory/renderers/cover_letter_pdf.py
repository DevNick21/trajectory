"""Cover letter → .pdf via reportlab."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from ..schemas import CoverLetterOutput


_SUBTLE = colors.HexColor("#444444")


def _styles():
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "cl_body",
        parent=base["Normal"],
        fontSize=11,
        leading=16,
        spaceAfter=10,
    )
    right = ParagraphStyle(
        "cl_right",
        parent=body,
        alignment=2,
        spaceAfter=18,
    )
    addr = ParagraphStyle("cl_addr", parent=body, spaceAfter=18)
    return {"body": body, "right": right, "addr": addr}


def _safe_filename(addressed_to: str) -> str:
    def clean(s: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return f"CoverLetter_{clean(addressed_to[:40])}_{ts}.pdf"


def render_cover_letter_pdf(
    cl: CoverLetterOutput,
    out_dir: Path,
    sender_name: str = "",
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _safe_filename(cl.addressed_to)

    st = _styles()
    story = []

    story.append(Paragraph(datetime.now().strftime("%d %B %Y"), st["right"]))
    story.append(Paragraph(cl.addressed_to.replace("\n", "<br/>"), st["addr"]))

    for para in cl.paragraphs:
        story.append(Paragraph(para, st["body"]))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Yours sincerely,", st["body"]))
    story.append(Spacer(1, 12 * mm))
    if sender_name:
        story.append(Paragraph(f"<b>{sender_name}</b>", st["body"]))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=25 * mm,
        rightMargin=25 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    doc.build(story)
    return out_path
