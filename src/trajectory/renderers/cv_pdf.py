"""CV → .pdf via reportlab.

Matches the docx layout: name header, contact, summary, experience,
education, skills. Produces an A4 document with narrow margins.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    HRFlowable,
)

from ..schemas import CVOutput


_HEADING_COLOR = colors.HexColor("#1A1A2E")
_SUBTLE = colors.HexColor("#666666")
_RULE_COLOR = colors.HexColor("#CCCCCC")

_L_MARGIN = 18 * mm
_R_MARGIN = 18 * mm
_T_MARGIN = 12 * mm
_B_MARGIN = 12 * mm


def _styles():
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "cv_name",
            parent=base["Normal"],
            fontSize=18,
            textColor=_HEADING_COLOR,
            fontName="Helvetica-Bold",
            alignment=1,
            spaceAfter=2,
        ),
        "contact": ParagraphStyle(
            "cv_contact",
            parent=base["Normal"],
            fontSize=9,
            textColor=_SUBTLE,
            alignment=1,
            spaceAfter=6,
        ),
        "section": ParagraphStyle(
            "cv_section",
            parent=base["Normal"],
            fontSize=9,
            textColor=_HEADING_COLOR,
            fontName="Helvetica-Bold",
            spaceBefore=10,
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "cv_body",
            parent=base["Normal"],
            fontSize=10,
            spaceAfter=3,
        ),
        "role_header": ParagraphStyle(
            "cv_role",
            parent=base["Normal"],
            fontSize=10,
            fontName="Helvetica-Bold",
            spaceBefore=6,
            spaceAfter=1,
        ),
        "bullet": ParagraphStyle(
            "cv_bullet",
            parent=base["Normal"],
            fontSize=10,
            leftIndent=12,
            bulletIndent=4,
            spaceAfter=1,
        ),
    }


def _contact_string(contact: dict) -> str:
    parts = []
    for key in ("email", "phone", "location", "linkedin", "github"):
        if val := contact.get(key):
            parts.append(str(val))
    return "  |  ".join(parts)


def _safe_filename(name: str, company: str = "") -> str:
    def clean(s: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    if company:
        return f"{clean(name)}_CV_{clean(company)}_{ts}.pdf"
    return f"{clean(name)}_CV_{ts}.pdf"


def render_cv_pdf(cv: CVOutput, out_dir: Path, company: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _safe_filename(cv.name, company)

    st = _styles()
    story = []

    # Name + contact
    story.append(Paragraph(cv.name, st["name"]))
    story.append(Paragraph(_contact_string(cv.contact), st["contact"]))

    # Summary
    story.append(Paragraph("PROFESSIONAL SUMMARY", st["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE_COLOR, spaceAfter=4))
    story.append(Paragraph(cv.professional_summary, st["body"]))

    # Experience
    story.append(Paragraph("EXPERIENCE", st["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE_COLOR, spaceAfter=4))
    for role in cv.experience:
        header = f"<b>{role.title}</b>  —  {role.company}"
        dates_html = f'<font color="#666666" size="9">{role.dates}</font>'
        story.append(Paragraph(f"{header}  {dates_html}", st["role_header"]))
        for bullet in role.bullets:
            story.append(Paragraph(f"• {bullet.text}", st["bullet"]))

    # Education
    story.append(Paragraph("EDUCATION", st["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE_COLOR, spaceAfter=4))
    for edu in cv.education:
        deg = edu.get("degree") or edu.get("qualification") or ""
        inst = edu.get("institution") or edu.get("school") or ""
        years = edu.get("dates") or edu.get("years") or ""
        dates_html = f'  <font color="#666666" size="9">{years}</font>' if years else ""
        story.append(Paragraph(f"<b>{deg}  —  {inst}</b>{dates_html}", st["body"]))

    # Skills
    story.append(Paragraph("SKILLS", st["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE_COLOR, spaceAfter=4))
    story.append(Paragraph("  ·  ".join(cv.skills), st["body"]))

    # Projects
    if cv.projects:
        story.append(Paragraph("PROJECTS", st["section"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=_RULE_COLOR, spaceAfter=4))
        for proj in cv.projects:
            name = proj.get("name") or "Project"
            desc = proj.get("description") or proj.get("summary") or ""
            text = f"<b>{name}</b> — {desc}" if desc else f"<b>{name}</b>"
            story.append(Paragraph(text, st["body"]))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=_L_MARGIN,
        rightMargin=_R_MARGIN,
        topMargin=_T_MARGIN,
        bottomMargin=_B_MARGIN,
    )
    doc.build(story)
    return out_path
