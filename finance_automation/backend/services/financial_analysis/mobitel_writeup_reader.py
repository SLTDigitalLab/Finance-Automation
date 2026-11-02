"""
Reader for Mobitel Management Write-up DOCX files.
Extracts narrative commentary for Executive Summary, Section A (YoY), Section B (QoQ),
Section C (YTD), Section D (Budget vs Actual), and specific line-item commentary.
"""
from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

import docx
from docx.document import Document

logger = logging.getLogger(__name__)


@dataclass
class MobitelWriteup:
    exec_summary: str = ""
    section_a_yoy: str = ""
    section_b_qoq: str = ""
    section_c_ytd: str = ""
    section_d_budget: str = ""
    revenue_commentary: str = ""
    opex_commentary: str = ""
    ebitda_commentary: str = ""
    raw_sections: Dict[str, List[str]] = field(default_factory=dict)
    source_filename: str = ""
    warnings: List[str] = field(default_factory=list)


class MobitelWriteupReader:
    """Parses a Mobitel Management Write-up (.docx) file."""

    def read(self, path: str | Path) -> MobitelWriteup:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Mobitel write-up file not found: {path}")

        doc = docx.Document(str(path))
        warnings: List[str] = []

        # 1. Identify section headings and paragraph ranges
        sections = self._parse_sections(doc, warnings)

        # 2. Extract section text strings
        section_a_paras = sections.get("A", [])
        section_b_paras = sections.get("B", [])
        section_c_paras = sections.get("C", [])
        section_d_paras = sections.get("D", [])
        exec_paras = sections.get("exec", [])

        section_a_yoy = "\n\n".join(section_a_paras)
        section_b_qoq = "\n\n".join(section_b_paras)
        section_c_ytd = "\n\n".join(section_c_paras)
        section_d_budget = "\n\n".join(section_d_paras)

        # 3. Handle Executive Summary
        if exec_paras:
            exec_summary = "\n\n".join(exec_paras)
        else:
            # If no explicit Executive Summary section in the document, synthesize from YoY/overview
            exec_summary = self._synthesize_exec_summary(section_a_paras, section_c_paras)
            if not exec_summary:
                warnings.append("No Executive Summary found in write-up; unable to synthesize.")

        # 4. Extract line-item commentaries across sections
        all_paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        rev_paras, opex_paras, ebitda_paras = self._extract_line_commentaries(all_paras)

        # Also store raw sections as dict of lists
        raw_sections = {
            "exec": exec_paras,
            "A": section_a_paras,
            "B": section_b_paras,
            "C": section_c_paras,
            "D": section_d_paras,
        }

        # Check for missing critical sections and warn
        if not section_a_yoy:
            warnings.append("Section A (YoY Quarter) commentary not found.")
        if not section_b_qoq:
            warnings.append("Section B (QoQ Quarter) commentary not found.")
        if not section_c_ytd:
            warnings.append("Section C (YTD) commentary not found.")
        if not section_d_budget:
            warnings.append("Section D (Budget vs Actual) commentary not found.")

        return MobitelWriteup(
            exec_summary=exec_summary,
            section_a_yoy=section_a_yoy,
            section_b_qoq=section_b_qoq,
            section_c_ytd=section_c_ytd,
            section_d_budget=section_d_budget,
            revenue_commentary="\n\n".join(rev_paras),
            opex_commentary="\n\n".join(opex_paras),
            ebitda_commentary="\n\n".join(ebitda_paras),
            raw_sections=raw_sections,
            source_filename=path.name,
            warnings=warnings,
        )

    def _is_heading_candidate(self, p: docx.text.paragraph.Paragraph) -> bool:
        text = p.text.strip()
        if not text:
            return False
        if p.style.name.startswith("Heading"):
            return True
        if len(text) > 180:
            return False
        # Matches patterns like "(A)", "A)", "Section A", "Performance of...", "1H 2026 Vs"
        if re.match(r"^\s*(\([A-Za-z0-9]\)|[A-Za-z0-9]\.|\bSection\s+[A-Za-z0-9]\b)", text, re.IGNORECASE):
            return True
        if any(k in text.lower() for k in [
            "performance of", "executive summary", "exec summary", "1h 2026 vs",
            "vs 1h", "actuals vs budget", "actuals against"
        ]):
            return True
        return False

    def _classify_heading(self, text: str) -> Optional[str]:
        t = text.lower().strip()
        # Clean leading numbering/bullets
        t_clean = re.sub(r"^(\([a-d0-9]\)|[a-d0-9]\.|\bsection\s+[a-d0-9]\b)\s*", "", t)

        # 1. Executive Summary
        if re.search(r"executive\s+summary|exec\s+summary|overview", t):
            return "exec"

        # 2. Budget vs Actuals -> Section D
        if re.search(r"actuals?\s*(vs|against).*budget|performance.*against.*budget|budget\s*vs\s*actuals?", t):
            return "D"

        # 3. QoQ (Current Quarter vs Preceding Quarter) -> Section B
        if re.search(r"preceding\s+quarter|previous\s+quarter|q-o-q|qoq|\bq[1-4]\s*['’\d]*\s*vs\s*q[1-4]", t):
            if not ("2025" in t or "same quarter" in t or "previous year" in t or "ly" in t):
                return "B"

        # 4. YTD (Current period against preceding year / 1H vs 1H) -> Section C
        if re.search(r"current\s+period.*preceding\s+year|1h\s*\d{4}\s*vs\s*1h|ytd\b|first\s+(six|nine|three)\s+months", t):
            return "C"

        # 5. YoY Quarter (Current Quarter vs Previous Year Quarter) -> Section A
        if re.search(r"previous\s+year\s+q\d|same\s+quarter|quarter.*preceding\s+year|quarter.*previous\s+year|q\d\s*20\d\d\s*vs\s*q\d\s*20\d\d", t):
            return "A"

        # Fallback by leading letter: "Section A" -> A, "Section B" -> B, etc.
        m = re.match(r"^\(?([a-d])\)?[\.\:\s]", t)
        if m:
            letter = m.group(1).upper()
            return letter

        return None

    def _parse_sections(self, doc: Document, warnings: List[str]) -> Dict[str, List[str]]:
        heading_indices: List[Tuple[int, str, str]] = []

        for i, p in enumerate(doc.paragraphs):
            txt = p.text.strip()
            if not txt:
                continue
            if self._is_heading_candidate(p):
                cat = self._classify_heading(txt)
                if cat:
                    heading_indices.append((i, cat, txt))

        sections: Dict[str, List[str]] = {"exec": [], "A": [], "B": [], "C": [], "D": []}

        for idx, (p_idx, cat, heading_txt) in enumerate(heading_indices):
            start = p_idx + 1
            end = heading_indices[idx + 1][0] if idx + 1 < len(heading_indices) else len(doc.paragraphs)
            body_paras: List[str] = []
            for k in range(start, end):
                para_txt = doc.paragraphs[k].text.strip()
                if para_txt:
                    body_paras.append(para_txt)
            sections[cat].extend(body_paras)

        return sections

    def _synthesize_exec_summary(self, sec_a_paras: List[str], sec_c_paras: List[str]) -> str:
        """
        Synthesizes an executive summary if the document does not contain an explicit heading.
        Takes top-level summary statements from Section A (YoY Quarter).
        """
        chosen: List[str] = []
        source_paras = sec_a_paras if sec_a_paras else sec_c_paras
        if not source_paras:
            return ""

        for p in source_paras:
            p_low = p.lower()
            if any(k in p_low for k in ["recorded a strong", "recorded a solid", "performance continued", "exceeded the budget"]):
                chosen.append(p)
            elif "operating expenses" in p_low or "operating cost" in p_low:
                chosen.append(p)
            elif "ebitda" in p_low and "margin" in p_low:
                chosen.append(p)
            elif p_low.startswith("overall,"):
                chosen.append(p)

        if not chosen:
            # Fallback to first 2 paragraphs
            chosen = source_paras[:2]

        return "\n\n".join(chosen[:4])

    def _extract_line_commentaries(self, paras: List[str]) -> Tuple[List[str], List[str], List[str]]:
        rev_paras: List[str] = []
        opex_paras: List[str] = []
        ebitda_paras: List[str] = []

        for p in paras:
            p_low = p.lower()
            if "revenue" in p_low and ("broadband" in p_low or "topline" in p_low or "arpu" in p_low or "subscribers" in p_low):
                rev_paras.append(p)
            if any(k in p_low for k in ["operating cost", "operating expense", "power & energy", "spectrum & license", "direct cost"]):
                opex_paras.append(p)
            if any(k in p_low for k in ["ebitda", "operating profit", "ebit margin", "profit before tax", "net profit"]):
                ebitda_paras.append(p)

        return rev_paras[:4], opex_paras[:4], ebitda_paras[:4]


def read_mobitel_writeup(path: str | Path) -> MobitelWriteup:
    """Helper function to read a Mobitel write-up DOCX file."""
    return MobitelWriteupReader().read(path)
