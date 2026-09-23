"""ATS-friendly resume PDF + DOCX generation (pure local generation).

Only content supplied by the user (profile, skills, and anything they typed)
is placed in the document — the generator never invents experience.
"""

from __future__ import annotations

import io

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

MARGIN = 54          # points
LINE_GAP = 4
SECTION_GAP = 10

BODY = 10
NAME_SIZE = 20
SECTION_SIZE = 11

SECTIONS = ("summary", "skills", "education", "experience", "projects",
            "certifications", "achievements")
TITLES = {"summary": "PROFESSIONAL SUMMARY", "skills": "SKILLS",
          "education": "EDUCATION", "experience": "EXPERIENCE",
          "projects": "PROJECTS", "certifications": "CERTIFICATIONS",
          "achievements": "ACHIEVEMENTS"}


def _clean(value, limit: int = 4000) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", "").strip()
    return text[:limit]


def _empty_content() -> dict:
    content = {"name": "", "contact": "", "summary": "", "education": ""}
    for key in ("skills", "certifications", "achievements"):
        content[key] = []
    content["experience"] = []
    content["projects"] = []
    return content


def normalise_content(raw: dict) -> dict:
    """Whitelist + clamp the incoming resume content (never trusts the client)."""
    raw = raw if isinstance(raw, dict) else {}
    content = _empty_content()
    content["name"] = _clean(raw.get("name"), 120)
    content["contact"] = _clean(raw.get("contact"), 300)
    content["summary"] = _clean(raw.get("summary"), 900)
    content["education"] = _clean(raw.get("education"), 900)

    for key in ("skills", "certifications", "achievements"):
        items = raw.get(key) or []
        if isinstance(items, str):
            items = [part.strip() for part in items.split(",") if part.strip()]
        content[key] = [_clean(item, 160) for item in items if _clean(item)][:20]

    for key in ("experience", "projects"):
        entries = raw.get(key) or []
        rows = []
        if isinstance(entries, list):
            for entry in entries[:12]:
                if not isinstance(entry, dict):
                    continue
                title = _clean(entry.get("title"), 120)
                org = _clean(entry.get("org") or entry.get("company") or entry.get("detail"), 160)
                period = _clean(entry.get("period"), 60)
                bullets = [_clean(b, 240) for b in (entry.get("bullets") or []) if _clean(b)][:5]
                if title or org:
                    rows.append({"title": title, "org": org, "period": period,
                                 "bullets": bullets})
        content[key] = rows
    return content

def build_pdf(content: dict) -> bytes:
    content = normalise_content(content)
    doc = fitz.open()
    page = doc.new_page()  # A4 default
    width, height = page.rect.width, page.rect.height
    x = MARGIN
    text_width = width - 2 * MARGIN
    y = MARGIN

    def need(space: float) -> None:
        nonlocal page, y
        if y + space > height - MARGIN:
            page = doc.new_page()
            y = MARGIN

    def paragraph(text: str, size: float = BODY, bold: bool = False,
                  color=(0.1, 0.12, 0.16), indent: float = 0.0) -> None:
        nonlocal y
        if not text:
            return
        font = "hebo" if bold else "helv"
        rect = fitz.Rect(x + indent, y, x + indent + text_width - indent, height - MARGIN)
        consumed = page.insert_textbox(rect, text, fontsize=size, fontname=font,
                                       color=color, lineheight=1.25)
        if consumed < 0:  # didn't fit — start a new page and retry
            need(size * 2)
            rect = fitz.Rect(x + indent, y, x + indent + text_width - indent, height - MARGIN)
            page.insert_textbox(rect, text, fontsize=size, fontname=font,
                                color=color, lineheight=1.25)
        lines = max(1, int(len(text) / max(1.0, (text_width - indent) / (size * 0.52))) + 1)
        y += lines * size * 1.32 + LINE_GAP

    paragraph(content["name"], size=NAME_SIZE, bold=True)
    if content["contact"]:
        paragraph(content["contact"], size=9.5, color=(0.35, 0.38, 0.45))
    y += 6

    for section in SECTIONS:
        entries = content[section]
        if isinstance(entries, list) and not entries:
            continue
        if isinstance(entries, str) and not entries:
            continue

        need(50)
        y += SECTION_GAP
        paragraph(TITLES[section], size=SECTION_SIZE, bold=True,
                  color=(0.16, 0.2, 0.55))
        page.draw_line(fitz.Point(x, y - 2), fitz.Point(x + text_width, y - 2),
                       color=(0.75, 0.78, 0.85), width=0.8)
        y += 8

        if section == "skills":
            paragraph(" • ".join(entries), size=BODY)
        elif section in ("experience", "projects"):
            for row in entries:
                heading = row["title"]
                if row["org"]:
                    heading = f"{heading} — {row['org']}" if heading else row["org"]
                if row["period"]:
                    heading = f"{heading} ({row['period']})" if heading else row["period"]
                paragraph(heading, size=BODY, bold=True)
                for bullet in row["bullets"]:
                    paragraph(f"• {bullet}", size=BODY, indent=10)
                y += 2
        elif isinstance(entries, list):
            for item in entries:
                paragraph(f"• {item}", size=BODY)
        else:
            paragraph(entries, size=BODY)

    data = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    return data

# ---------------------------------------------------------------------------
# DOCX generation (built from scratch — no external dependencies).
# A .docx is a ZIP of XML parts; writing it directly keeps the dependency list
# minimal while still producing a file Word/Google Docs can open.
# ---------------------------------------------------------------------------


def _xml_escape(value) -> str:
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _docx_paragraph(text: str, bold: bool = False, size: int = 21,
                    color: str = "1A1F2B", space_after: int = 60) -> str:
    """One WordprocessingML paragraph (size is in half-points)."""
    props = (f'<w:pPr><w:spacing w:after="{space_after}"/></w:pPr>')
    run_props = (f'<w:rPr><w:sz w:val="{size}"/>'
                 f'<w:szCs w:val="{size}"/>'
                 f'<w:color w:val="{color}"/>'
                 + ('<w:b/>' if bold else '') + '</w:rPr>')
    return (f'<w:p>{props}<w:r>{run_props}'
            f'<w:t xml:space="preserve">{_xml_escape(text)}</w:t></w:r></w:p>')


def _docx_heading(text: str) -> str:
    return _docx_paragraph(text.upper(), bold=True, size=24, color="243B93",
                           space_after=40)


def build_docx(content: dict) -> bytes:
    """Render the resume content as a single-column, ATS-friendly .docx."""
    import zipfile

    content = normalise_content(content)
    parts: list = []

    if content["name"]:
        parts.append(_docx_paragraph(content["name"], bold=True, size=34,
                                     color="111827", space_after=20))
    if content["contact"]:
        parts.append(_docx_paragraph(content["contact"], size=19, color="4B5563"))

    for section in SECTIONS:
        entries = content[section]
        if isinstance(entries, list) and not entries:
            continue
        if isinstance(entries, str) and not entries:
            continue
        parts.append(_docx_heading(TITLES[section]))

        if section == "skills":
            parts.append(_docx_paragraph(" • ".join(entries)))
        elif section in ("experience", "projects"):
            for row in entries:
                heading = row["title"]
                if row["org"]:
                    heading = f"{heading} — {row['org']}" if heading else row["org"]
                if row["period"]:
                    heading = f"{heading} ({row['period']})" if heading else row["period"]
                parts.append(_docx_paragraph(heading, bold=True))
                for bullet in row["bullets"]:
                    parts.append(_docx_paragraph(f"• {bullet}"))
        elif isinstance(entries, list):
            for item in entries:
                parts.append(_docx_paragraph(f"• {item}"))
        else:
            parts.append(_docx_paragraph(entries))

    body = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
            "<w:body>" + "".join(parts) +
            "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
            "<w:pgMar w:top=\"1134\" w:right=\"1134\" w:bottom=\"1134\" w:left=\"1134\"/>"
            "</w:sectPr></w:body></w:document>")

    content_types = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                     "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
                     "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
                     "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
                     "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
                     "</Types>")
    rels = ("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
            "</Relationships>")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", body)
    return buffer.getvalue()

