"""
Professional document restructuring using w:pageBreakBefore and clean typography.
Eliminates all blank pages completely.
"""
import re
from pathlib import Path
import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

PRINTABLE_WIDTH_DXA = 9540

def _text(el):
    return "".join(t.text or "" for t in el.iter(qn("w:t"))).strip()

def _norm(txt):
    return re.sub(r"[^a-z0-9]", "", (txt or "").lower())

def add_cant_split(tr):
    trPr = tr.find(qn("w:trPr"))
    if trPr is None:
        trPr = OxmlElement("w:trPr")
        tr.insert(0, trPr)
    if trPr.find(qn("w:cantSplit")) is None:
        trPr.append(OxmlElement("w:cantSplit"))

def add_tbl_header(tr):
    trPr = tr.find(qn("w:trPr"))
    if trPr is None:
        trPr = OxmlElement("w:trPr")
        tr.insert(0, trPr)
    if trPr.find(qn("w:tblHeader")) is None:
        trPr.append(OxmlElement("w:tblHeader"))

def add_keep_with_next(p):
    pPr = p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        p.insert(0, pPr)
    if pPr.find(qn("w:keepNext")) is None:
        pPr.append(OxmlElement("w:keepNext"))
    if pPr.find(qn("w:keepLines")) is None:
        pPr.append(OxmlElement("w:keepLines"))

def remove_keep_with_next(p):
    pPr = p.find(qn("w:pPr"))
    if pPr is not None:
        kn = pPr.find(qn("w:keepNext"))
        if kn is not None:
            pPr.remove(kn)

def set_page_break_before(p):
    pPr = p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        p.insert(0, pPr)
    if pPr.find(qn("w:pageBreakBefore")) is None:
        pPr.append(OxmlElement("w:pageBreakBefore"))

def remove_page_break_before(p):
    pPr = p.find(qn("w:pPr"))
    if pPr is not None:
        pbb = pPr.find(qn("w:pageBreakBefore"))
        if pbb is not None:
            pPr.remove(pbb)

def restructure_no_blank_pages(doc):
    body = doc.element.body

    # -------------------------------------------------------------
    # 1. Format Tables: center, scale wide tables, tblHeader, cantSplit
    # -------------------------------------------------------------
    for t in doc.tables:
        tbl_el = t._element
        tblPr = tbl_el.find(qn("w:tblPr"))
        if tblPr is None:
            tblPr = OxmlElement("w:tblPr")
            tbl_el.insert(0, tblPr)

        # Center table
        jc = tblPr.find(qn("w:jc"))
        if jc is None:
            jc = OxmlElement("w:jc")
            tblPr.append(jc)
        jc.set(qn("w:val"), "center")

        # Column scaling if wider than printable area
        grid = tbl_el.find(qn("w:tblGrid"))
        if grid is not None:
            cols = grid.findall(qn("w:gridCol"))
            widths = [int(c.get(qn("w:w"))) for c in cols if c.get(qn("w:w")) and c.get(qn("w:w")).isdigit()]
            total_w = sum(widths)
            if total_w > PRINTABLE_WIDTH_DXA:
                scale = PRINTABLE_WIDTH_DXA / total_w
                new_widths = [int(round(w * scale)) for w in widths]
                diff = PRINTABLE_WIDTH_DXA - sum(new_widths)
                if new_widths:
                    new_widths[-1] += diff
                for c, nw in zip(cols, new_widths):
                    c.set(qn("w:w"), str(nw))

                tblW = tblPr.find(qn("w:tblW"))
                if tblW is not None:
                    tblW.set(qn("w:w"), str(PRINTABLE_WIDTH_DXA))
                    tblW.set(qn("w:type"), "dxa")

                for tr in tbl_el.findall(qn("w:tr")):
                    col_idx = 0
                    for tc in tr.findall(qn("w:tc")):
                        tcPr = tc.find(qn("w:tcPr"))
                        if tcPr is not None:
                            span_el = tcPr.find(qn("w:gridSpan"))
                            span = int(span_el.get(qn("w:val"))) if span_el is not None else 1
                            cell_w = sum(new_widths[col_idx:col_idx + span])
                            tcW = tcPr.find(qn("w:tcW"))
                            if tcW is not None:
                                tcW.set(qn("w:w"), str(cell_w))
                                tcW.set(qn("w:type"), "dxa")
                            col_idx += span

        # Fixed layout
        old_layout = tblPr.find(qn("w:tblLayout"))
        if old_layout is not None:
            tblPr.remove(old_layout)
        layout = tblPr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
        tblPr.append(layout)

        # cantSplit on every row (prevents mid-row split)
        # tblHeader on header rows (repeats header across pages)
        rows = tbl_el.findall(qn("w:tr"))
        num_rows = len(rows)
        num_cols = len(t.columns) if t.columns else (len(grid.findall(qn("w:gridCol"))) if grid is not None else 0)
        header_row_count = 2 if (num_cols > 10 and num_rows > 3) else 1

        for r_i, tr in enumerate(rows):
            add_cant_split(tr)
            if r_i < header_row_count:
                add_tbl_header(tr)

            # Ensure NO keepNext inside table cells (never bind rows together with keepNext)
            for tc in tr.findall(qn("w:tc")):
                for p in tc.findall(qn("w:p")):
                    remove_keep_with_next(p)

    # -------------------------------------------------------------
    # 2. Section Headings that should start on a fresh page
    #    Use w:pageBreakBefore ON THE PARAGRAPH ITSELF (never separate empty break paragraphs!)
    # -------------------------------------------------------------
    major_section_headings = [
        "performanceofthecurrentquarteragainsttheprecedingyear",
        "bperformanceofthecurrentquarteragainsttheprecedingquarter",
        "performanceofthecurrentyearagainsttheprecedingyear",
        "dperformanceofthecurrentquarteractualsagainstthebudget",
        "annexureiborrowingsrepaymentschedule",
        "annexureiiaccountlevelvariancedrivers",
    ]

    heading_keywords = [
        "executivesummary", "sltgroup", "sltplc", "mobitel",
        "financialstatistics", "financialsummary", "keyratios",
        "operationalstatistics", "keydrivers", "capacityvsutilization",
        "performanceof", "bperformanceof", "dperformanceof",
        "incomestatement", "revenue", "opex", "profits",
        "liquidityandoperatingcashflow", "borrowings", "interestcost",
        "keyprojectsinfo", "ftthportutilization", "ftthrtwomwise", "ftthactive",
        "annexure", "sectionstobecompleted", "datanotes"
    ]

    children = list(body)

    # Find cover end (where Executive Summary is)
    exec_idx = -1
    for i, el in enumerate(children):
        if el.tag == qn("w:p") and _norm(_text(el)) == "executivesummary":
            exec_idx = i
            break

    # Clean the cover page: keep top banners and bottom "Finance Group" banner
    # In orig.docx, there were 25 empty lines. Reduce them so the cover page NEVER spills onto page 2!
    cover_elements = children[:exec_idx] if exec_idx > 0 else []
    clean_cover = []
    empty_cover_count = 0
    for el in cover_elements:
        if el.tag == qn("w:p"):
            txt = _text(el)
            drawings = list(el.iter(qn("w:drawing")))
            if not txt and not drawings:
                empty_cover_count += 1
                # Keep exactly 14 empty paragraphs (optimal vertical spacing for Finance Group on Page 1)
                if empty_cover_count <= 14:
                    clean_cover.append(el)
                continue
            clean_cover.append(el)
        else:
            clean_cover.append(el)

    # Executive Summary paragraph starts page 2 cleanly via pageBreakBefore
    rest_elements = children[exec_idx:] if exec_idx > 0 else children

    # Process all elements from exec_idx onwards
    cleaned_rest = []
    consec_empty = 0
    for i, el in enumerate(rest_elements):
        tag = el.tag.split("}")[-1]
        if tag == "sectPr":
            continue

        if tag == "tbl":
            cleaned_rest.append(el)
            consec_empty = 0
            continue

        if tag == "p":
            # Remove any explicit page breaks (<w:br w:type="page"/>)
            # We use w:pageBreakBefore on headings instead, which never produces blank pages!
            for br in list(el.iter(qn("w:br"))):
                if br.get(qn("w:type")) == "page":
                    br.getparent().remove(br)

            txt = _text(el)
            t_norm = _norm(txt)
            drawings = list(el.iter(qn("w:drawing")))

            # Check if paragraph is purely empty
            if not txt and not drawings:
                consec_empty += 1
                # Drop empty paragraphs adjacent to tables or headings
                if i + 1 < len(rest_elements):
                    next_el = rest_elements[i + 1]
                    if next_el.tag == qn("w:tbl"):
                        continue
                    next_txt = _norm(_text(next_el))
                    if any(k in next_txt for k in heading_keywords):
                        continue
                if consec_empty <= 1:
                    cleaned_rest.append(el)
                continue

            consec_empty = 0

            # Check if this paragraph should have pageBreakBefore
            is_major = False
            for target in major_section_headings:
                if t_norm.startswith(target) or target in t_norm:
                    is_major = True
                    break

            if is_major or t_norm == "executivesummary":
                set_page_break_before(el)
            else:
                remove_page_break_before(el)

            cleaned_rest.append(el)

    # Combine cover + rest
    all_cleaned = clean_cover + cleaned_rest

    # Remove any trailing empty paragraphs at the end of the document
    while all_cleaned and all_cleaned[-1].tag == qn("w:p"):
        last_p = all_cleaned[-1]
        if not _text(last_p) and not list(last_p.iter(qn("w:drawing"))):
            all_cleaned.pop()
        else:
            break

    # Pass 2: Apply keepNext on headings and paragraphs preceding tables
    n_all = len(all_cleaned)
    for j, el in enumerate(all_cleaned):
        if el.tag != qn("w:p"):
            continue

        # Drawings never get keepNext
        if list(el.iter(qn("w:drawing"))):
            remove_keep_with_next(el)
            continue

        txt = _text(el)
        if not txt:
            remove_keep_with_next(el)
            continue

        t_norm = _norm(txt)
        is_heading = any(k in t_norm for k in heading_keywords)
        next_is_tbl = (j + 1 < n_all and all_cleaned[j + 1].tag == qn("w:tbl"))
        next_next_is_tbl = (j + 2 < n_all and all_cleaned[j + 2].tag == qn("w:tbl"))
        next_is_caption = (j + 1 < n_all and all_cleaned[j + 1].tag == qn("w:p") and len(_text(all_cleaned[j + 1])) < 40)

        if is_heading or next_is_tbl or (next_next_is_tbl and next_is_caption):
            add_keep_with_next(el)
        else:
            remove_keep_with_next(el)
            # prevent orphan single lines in body
            pPr = el.find(qn("w:pPr"))
            if pPr is not None and pPr.find(qn("w:keepLines")) is None:
                pPr.append(OxmlElement("w:keepLines"))

    # Rebuild body
    sectPr = body.find(qn("w:sectPr"))
    for c in list(body):
        body.remove(c)
    for c in all_cleaned:
        body.append(c)
    if sectPr is not None:
        body.append(sectPr)

def execute():
    target = Path(r"..\input bord pack\Output file_Q2 2026 Analysis.docx").resolve()
    print("Loading clean orig.docx...")
    doc = docx.Document("orig.docx")
    print("Applying restructuring with pageBreakBefore (zero blank pages)...")
    restructure_no_blank_pages(doc)
    doc.save(str(target))
    print(f"Successfully saved to {target}")

if __name__ == "__main__":
    execute()
