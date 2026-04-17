"""PDF report generator using fpdf2."""
from __future__ import annotations

import io
import os
import re
import tempfile
import unicodedata
from datetime import datetime

from fpdf import FPDF


# ── Colours ──────────────────────────────────────────────────────────────────
_C_DARK    = (30,  30,  30)
_C_BODY    = (55,  55,  55)
_C_MUTED   = (130, 130, 130)
_C_ACCENT  = (30,  90,  160)   # blue
_C_RULE    = (210, 210, 210)


def _clean(text: str) -> str:
    """Strip Discord markdown and coerce all text to Latin-1 safe characters."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)          # **bold**
    text = re.sub(r'\*(.+?)\*',     r'\1', text)           # *italic*
    text = re.sub(r'`(.+?)`',       r'\1', text)           # `code`
    text = re.sub(r'^> ',           '  ',  text, flags=re.MULTILINE)

    _replacements = {
        '\u2501': '-', '\u2500': '-', '\u2502': '|',
        '\u2014': '--', '\u2013': '-',
        '\u2019': "'", '\u2018': "'",
        '\u201c': '"', '\u201d': '"',
        '\u2022': '-', '\u2023': '-', '\u2026': '...',
        '\u26a0': '!', '\u2705': '[OK]', '\u274c': '[X]',
        '\u2192': '->', '\u2190': '<-', '\u2193': 'v', '\u2191': '^',
        '\u00b7': '-', '\u2212': '-',
    }
    for char, replacement in _replacements.items():
        text = text.replace(char, replacement)

    # For anything still outside Latin-1, try NFKD decomposition then drop remainder
    result = []
    for char in text:
        try:
            char.encode('latin-1')
            result.append(char)
        except UnicodeEncodeError:
            decomposed = unicodedata.normalize('NFKD', char)
            ascii_fallback = decomposed.encode('ascii', errors='ignore').decode('ascii')
            result.append(ascii_fallback if ascii_fallback else '-')
    return ''.join(result)


def _is_divider_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r'^-{5,}', stripped) or re.match(r'^={5,}', stripped))


def _extract_section_title(line: str) -> str | None:
    """Extract a section title from a cleaned divider line like '--- PORTFOLIO ---'."""
    match = re.search(r'[A-Z][A-Z &/\-]+', line)
    return match.group().strip() if match else None


class _PDF(FPDF):
    _report_title: str = ""

    def multi_cell(self, w, h=None, text="", **kwargs):
        kwargs.setdefault("new_x", "LMARGIN")
        return super().multi_cell(w, h, text, **kwargs)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(*_C_MUTED)
        self.cell(0, 6, self._report_title, align='L')
        self.set_x(-30)
        self.set_font('Helvetica', '', 8)
        self.cell(20, 6, f'Page {self.page_no()}', align='R')
        self.ln(2)
        self.set_draw_color(*_C_RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', '', 7)
        self.set_text_color(*_C_MUTED)
        ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        self.cell(0, 6, f'Finance Digest  |  {ts}  |  Page {self.page_no()}', align='C')


def build_pdf(title: str, sections: list[str], subtitle: str = "") -> io.BytesIO:
    """
    Convert a list of text sections into a formatted PDF.
    Returns a BytesIO buffer ready to pass to discord.File.
    """
    pdf = _PDF(orientation='P', unit='mm', format='A4')
    pdf._report_title = _clean(title)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    # ── Cover / Title block ───────────────────────────────────────────────────
    pdf.ln(6)
    pdf.set_font('Helvetica', 'B', 22)
    pdf.set_text_color(*_C_ACCENT)
    pdf.multi_cell(0, 10, _clean(title))

    if subtitle:
        pdf.ln(1)
        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(*_C_MUTED)
        pdf.multi_cell(0, 6, _clean(subtitle))

    pdf.ln(2)
    pdf.set_draw_color(*_C_ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(6)

    # ── Body sections ─────────────────────────────────────────────────────────
    for raw_section in sections:
        section = _clean(raw_section)
        lines = section.split('\n')

        for line in lines:
            stripped = line.strip()

            if not stripped:
                pdf.ln(2)
                continue

            # Markdown horizontal rule  ---
            if re.match(r'^-{3,}$', stripped) or re.match(r'^={3,}$', stripped):
                pdf.ln(2)
                pdf.set_draw_color(*_C_RULE)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                pdf.ln(3)
                continue

            # Section divider  e.g. "--- PORTFOLIO ---"
            if _is_divider_line(stripped):
                pdf.ln(3)
                pdf.set_draw_color(*_C_RULE)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                pdf.ln(3)
                section_title = _extract_section_title(stripped)
                if section_title:
                    pdf.set_font('Helvetica', 'B', 13)
                    pdf.set_text_color(*_C_ACCENT)
                    pdf.cell(0, 7, section_title, ln=True)
                    pdf.ln(1)
                continue

            # Markdown headings  # ## ### ####
            h_match = re.match(r'^(#{1,4})\s+(.+)', stripped)
            if h_match:
                level = len(h_match.group(1))
                text  = h_match.group(2)
                if level == 1:
                    pdf.ln(4)
                    pdf.set_font('Helvetica', 'B', 16)
                    pdf.set_text_color(*_C_ACCENT)
                    pdf.multi_cell(0, 9, text)
                    pdf.set_draw_color(*_C_ACCENT)
                    pdf.set_line_width(0.4)
                    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                    pdf.set_line_width(0.2)
                    pdf.ln(3)
                elif level == 2:
                    pdf.ln(3)
                    pdf.set_font('Helvetica', 'B', 13)
                    pdf.set_text_color(*_C_ACCENT)
                    pdf.multi_cell(0, 8, text)
                    pdf.ln(1)
                elif level == 3:
                    pdf.ln(3)
                    pdf.set_font('Helvetica', 'B', 11)
                    pdf.set_text_color(*_C_DARK)
                    pdf.multi_cell(0, 7, text)
                    pdf.ln(1)
                else:
                    pdf.ln(2)
                    pdf.set_font('Helvetica', 'BI', 10)
                    pdf.set_text_color(*_C_BODY)
                    pdf.multi_cell(0, 6, text)
                continue

            # Numbered list items  e.g. "1. Some text"
            num_match = re.match(r'^(\d+)\.\s+(.+)', stripped)
            if num_match:
                pdf.set_font('Helvetica', 'B', 10)
                pdf.set_text_color(*_C_ACCENT)
                pdf.set_x(pdf.l_margin)
                pdf.cell(8, 5, num_match.group(1) + '.', ln=False)
                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(*_C_BODY)
                pdf.multi_cell(0, 5, num_match.group(2))
                continue

            # Bullet points  - or *
            if re.match(r'^[-*]\s+', stripped):
                text = re.sub(r'^[-*]\s+', '', stripped)
                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(*_C_BODY)
                pdf.set_x(pdf.l_margin + 4)
                pdf.cell(4, 5, '-', ln=False)
                pdf.multi_cell(0, 5, text)
                continue

            # VERDICT / CONCLUSION labels
            if re.match(r'^(VERDICT|CONCLUSION|SUMMARY)[:\s]', stripped, re.IGNORECASE):
                pdf.ln(2)
                pdf.set_font('Helvetica', 'B', 10)
                pdf.set_text_color(*_C_ACCENT)
                pdf.multi_cell(0, 6, stripped)
                pdf.ln(1)
                continue

            # Default body text
            pdf.set_font('Helvetica', '', 10)
            pdf.set_text_color(*_C_BODY)
            pdf.multi_cell(0, 5, stripped)

        pdf.ln(2)

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        pdf.output(tmp_path)
        with open(tmp_path, 'rb') as f:
            buffer = io.BytesIO(f.read())
    finally:
        os.unlink(tmp_path)
    buffer.seek(0)
    return buffer


def build_paper_pdf(
    title: str,
    sections: list[str],
    value_chart_buf: io.BytesIO,
    allocation_chart_buf: io.BytesIO,
    subtitle: str = "",
) -> io.BytesIO:
    """
    Paper trading report PDF — same text rendering as build_pdf but with two
    embedded matplotlib chart images (portfolio value vs SPY + allocation history).
    """
    pdf = _PDF(orientation='P', unit='mm', format='A4')
    pdf._report_title = _clean(title)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    # Title block
    pdf.ln(6)
    pdf.set_font('Helvetica', 'B', 22)
    pdf.set_text_color(*_C_ACCENT)
    pdf.multi_cell(0, 10, _clean(title))
    if subtitle:
        pdf.ln(1)
        pdf.set_font('Helvetica', '', 10)
        pdf.set_text_color(*_C_MUTED)
        pdf.multi_cell(0, 6, _clean(subtitle))
    pdf.ln(2)
    pdf.set_draw_color(*_C_ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(6)

    # Text sections (reuse same rendering logic as build_pdf)
    def _embed_chart(chart_buf: io.BytesIO, section_title: str) -> None:
        pdf.ln(4)
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(*_C_ACCENT)
        pdf.cell(0, 7, section_title, ln=True)
        pdf.set_draw_color(*_C_RULE)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
        chart_buf.seek(0)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_img:
            tmp_img.write(chart_buf.read())
            tmp_img_path = tmp_img.name
        try:
            chart_w = pdf.w - pdf.l_margin - pdf.r_margin
            pdf.image(tmp_img_path, x=pdf.l_margin, w=chart_w)
        finally:
            os.unlink(tmp_img_path)
        pdf.ln(4)

    # Render text sections first
    for section in sections:
        for raw_line in section.split('\n'):
            stripped = _clean(raw_line).strip()
            if not stripped:
                pdf.ln(2)
                continue

            if re.match(r'^#{1,4}\s', stripped):
                level = len(re.match(r'^(#+)', stripped).group(1))
                text = re.sub(r'^#+\s*', '', stripped)
                sizes = {1: (18, 'B'), 2: (15, 'B'), 3: (12, 'B'), 4: (11, 'B')}
                sz, style = sizes.get(level, (10, ''))
                pdf.ln(3 if level <= 2 else 1)
                pdf.set_font('Helvetica', style, sz)
                pdf.set_text_color(*(_C_ACCENT if level <= 2 else _C_DARK))
                pdf.multi_cell(0, 7 if level <= 2 else 6, text)
                continue

            if re.match(r'^(---|===)', stripped):
                title_text = _extract_section_title(stripped)
                pdf.ln(5)
                pdf.set_draw_color(*_C_RULE)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                if title_text:
                    pdf.ln(2)
                    pdf.set_font('Helvetica', 'B', 11)
                    pdf.set_text_color(*_C_DARK)
                    pdf.cell(0, 6, title_text, ln=True)
                pdf.ln(2)
                continue

            if re.match(r'^\d+\.\s+', stripped):
                text = re.sub(r'^\d+\.\s+', '', stripped)
                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(*_C_BODY)
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(0, 5, text)
                continue

            if re.match(r'^[-*]\s+', stripped):
                text = re.sub(r'^[-*]\s+', '', stripped)
                pdf.set_font('Helvetica', '', 10)
                pdf.set_text_color(*_C_BODY)
                pdf.set_x(pdf.l_margin + 4)
                pdf.cell(4, 5, '-', ln=False)
                pdf.multi_cell(0, 5, text)
                continue

            if re.match(r'^(VERDICT|CONCLUSION|SUMMARY|PRICE CHECK|NEWS IMPACT|KEY RISK|MONITOR|PRICE ACTION|FUNDAMENTAL SIGNAL|THESIS CHECK|KEY RISKS)[:\s]', stripped, re.IGNORECASE):
                pdf.ln(2)
                pdf.set_font('Helvetica', 'B', 10)
                pdf.set_text_color(*_C_ACCENT)
                pdf.multi_cell(0, 6, stripped)
                pdf.ln(1)
                continue

            pdf.set_font('Helvetica', '', 10)
            pdf.set_text_color(*_C_BODY)
            pdf.multi_cell(0, 5, stripped)

        pdf.ln(2)

    # Charts on a new page
    pdf.add_page()
    _embed_chart(value_chart_buf, "Portfolio Value vs SPY Benchmark")
    _embed_chart(allocation_chart_buf, "Historical Portfolio Allocation")

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        pdf.output(tmp_path)
        with open(tmp_path, 'rb') as f:
            buffer = io.BytesIO(f.read())
    finally:
        os.unlink(tmp_path)
    buffer.seek(0)
    return buffer


def filename(prefix: str, ticker: str = "") -> str:
    """Generate a timestamped filename for the PDF attachment."""
    date = datetime.utcnow().strftime('%Y-%m-%d')
    parts = ['finance', prefix]
    if ticker:
        parts.append(ticker.upper())
    parts.append(date)
    return '_'.join(parts) + '.pdf'
