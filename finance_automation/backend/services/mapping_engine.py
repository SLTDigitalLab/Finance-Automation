import re
import pandas as pd
import openpyxl
from typing import List, Dict, Tuple, Optional
from utils.logger import logger
from config import settings


def _normalize_category(raw: str) -> str:
    """Map raw mapping-sheet category names to exact slide category names."""
    if not raw:
        return raw

    s = raw.strip()

    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u2015", "-")

    s = re.sub(r"  +", " ", s)
    s = s.strip()

    _MAP = {
        "Copper - Voice": "Copper - Voice",
        "Copper  - Voice": "Copper - Voice",
        "LTE - Voice": "LTE - Voice",
        "LTE       - Voice": "LTE - Voice",
        "LTE     - Voice": "LTE - Voice",
        "LTE  - Voice": "LTE - Voice",
        "FTTH - Voice": "FTTH - Voice",
        "FTTH    - Voice": "FTTH - Voice",
        "FTTH  - Voice": "FTTH - Voice",
        "Interconnection": "Interconnection",
        "Copper - BB (without Wi-Fi PP)": "Copper - BB (without Wi-Fi PP)",
        "Copper – BB (without Wi-Fi PP)": "Copper - BB (without Wi-Fi PP)",
        "Wi-Fi Prepaid Cards": "Wi-Fi Prepaid Cards",
        "LTE - BB": "LTE - BB",
        "LTE–BB": "LTE - BB",
        "LTE-BB": "LTE - BB",
        "FTTH - BB": "FTTH - BB",
        "FTTH–BB": "FTTH - BB",
        "FTTH-BB": "FTTH - BB",
        "On Line Top-Up Usage": "On Line Top-Up Usage",
        "PEO TV": "PEO TV",
        "Enterprise (Corp. & Govt.)": "Enterprise (Corp. & Govt.)",
        "Carrier Domestic": "Carrier Domestic",
        "SME": "SME",
        "Micro Business": "Micro Business",
        "RAM & Retail": "RAM & Retail",
        "Digital Services": "Digital Services",
        "Equipment Sales": "Equipment Sales",
        "International": "International",
    }

    if s in _MAP:
        return _MAP[s]

    norm_lower = s.lower().strip()
    for slide_cat in settings.SLIDE_CATEGORIES:
        if slide_cat.lower() == norm_lower:
            return slide_cat

    intl_codes = {"3.1-2", "3.1-1", "3.2", "3.3", "3.4", "3-1", "3-2", "3-3", "3-4"}
    if s in intl_codes or norm_lower in intl_codes:
        return "International"

    return s


class MappingRule:
    def __init__(self):
        self.category: str = ""
        self.sub_category: str = ""
        self.section_code: str = ""
        self.cost_centre_from: Optional[int] = None
        self.cost_centre_to: Optional[int] = None
        self.product_from: Optional[int] = None
        self.product_to: Optional[int] = None
        self.account_from: Optional[int] = None
        self.account_to: Optional[int] = None
        self.tech_from: Optional[int] = None
        self.tech_to: Optional[int] = None
        self.business_line_from: Optional[int] = None
        self.business_line_to: Optional[int] = None

    def matches(self, row: dict) -> bool:
        segments = row.get("flexfield", "").split(".")
        if len(segments) < 9:
            return False

        cc = _safe_int(segments[1]) or 0
        bl = _safe_int(segments[3]) or 0
        prod = _safe_int(segments[4]) or 0
        acct = _safe_int(segments[5]) or 0
        tech = _safe_int(segments[6]) or 0

        cc_to = (
            self.cost_centre_to
            if self.cost_centre_to is not None
            else self.cost_centre_from
        )
        prod_to = self.product_to if self.product_to is not None else self.product_from
        acct_to = self.account_to if self.account_to is not None else self.account_from
        tech_to = self.tech_to if self.tech_to is not None else self.tech_from
        bl_to = (
            self.business_line_to
            if self.business_line_to is not None
            else self.business_line_from
        )

        if self.cost_centre_from is not None and cc_to is not None:
            if not (self.cost_centre_from <= cc <= cc_to):
                return False

        if self.product_from is not None and prod_to is not None:
            if not (self.product_from <= prod <= prod_to):
                return False

        if self.account_from is not None and acct_to is not None:
            if not (self.account_from <= acct <= acct_to):
                return False

        if self.tech_from is not None and tech_to is not None:
            if not (self.tech_from <= tech <= tech_to):
                return False

        if self.business_line_from is not None and bl_to is not None:
            if not (self.business_line_from <= bl <= bl_to):
                return False

        return True

    def specificity_score(self) -> int:
        score = 0
        if self.cost_centre_from is not None:
            score += 1
        if self.product_from is not None:
            score += 1
        if self.account_from is not None:
            score += 1
        if self.tech_from is not None:
            score += 1
        if self.business_line_from is not None:
            score += 1
        return score


class MappingEngine:
    def __init__(self):
        self.rules: List[MappingRule] = []
        self.section_headers: Dict[int, str] = {}
        self.section_codes: Dict[int, str] = {}
        self.unmapped_rows: List[dict] = []
        self.unmapped_reasons: List[str] = []
        self.category_to_row_map: Dict[str, str] = {}

    def load_mapping(self, mapping_path: str):
        wb = openpyxl.load_workbook(mapping_path, read_only=True, data_only=True)
        ws = wb["Code Mapping"]

        current_section = ""
        current_section_code = ""
        data_row_started = False
        header_row = 3

        for row_idx, row in enumerate(
            ws.iter_rows(min_row=4, values_only=True), start=4
        ):
            col_a = row[0] if len(row) > 0 else None
            col_b = row[1] if len(row) > 1 else None
            col_c = row[2] if len(row) > 2 else None
            col_d = row[3] if len(row) > 3 else None
            col_e = row[4] if len(row) > 4 else None
            col_f = row[5] if len(row) > 5 else None
            col_g = row[6] if len(row) > 6 else None
            col_h = row[7] if len(row) > 7 else None
            col_i = row[8] if len(row) > 8 else None
            col_j = row[9] if len(row) > 9 else None
            col_k = row[10] if len(row) > 10 else None
            col_l = row[11] if len(row) > 11 else None

            b_str = str(col_b).strip() if col_b else ""

            is_section_header = False
            if b_str and (
                "." in b_str
                or b_str in ["1-1", "1-2", "1-3", "1-4", "1-5"]
                or b_str.startswith("2-")
                or b_str.startswith("3.")
                or b_str.startswith("3-")
                or b_str == "Global SBU"
            ):
                is_section_header = True
            if col_a is not None and col_e is None and col_g is None and col_k is None:
                a_str = str(col_a).strip()
                if a_str and not a_str.replace(".", "").isdigit():
                    is_section_header = True

            if is_section_header:
                if col_a is not None:
                    a_str = str(col_a).strip()
                    if a_str and not a_str.replace(".", "").isdigit():
                        current_section = _normalize_category(a_str)
                        current_section_code = b_str
                elif col_c is not None:
                    c_str = str(col_c).strip()
                    if c_str:
                        current_section_code = b_str
                continue

            has_any_range = any(
                v is not None
                for v in [
                    col_c,
                    col_d,
                    col_e,
                    col_f,
                    col_g,
                    col_h,
                    col_i,
                    col_j,
                    col_k,
                    col_l,
                ]
            )
            has_numeric_a = False
            if col_a is not None:
                try:
                    float(col_a)
                    has_numeric_a = True
                except (ValueError, TypeError):
                    pass

            if has_numeric_a and (has_any_range or col_b is not None):
                rule = MappingRule()
                rule.category = current_section
                rule.section_code = current_section_code

                if col_b is not None:
                    rule.sub_category = str(col_b).strip()

                rule.cost_centre_from = _safe_int(col_c)
                rule.cost_centre_to = (
                    _safe_int(col_d) if col_d is not None else rule.cost_centre_from
                )
                rule.product_from = _safe_int(col_e)
                rule.product_to = (
                    _safe_int(col_f) if col_f is not None else rule.product_from
                )
                rule.account_from = _safe_int(col_g)
                rule.account_to = (
                    _safe_int(col_h) if col_h is not None else rule.account_from
                )
                rule.tech_from = _safe_int(col_i)
                rule.tech_to = _safe_int(col_j) if col_j is not None else rule.tech_from
                rule.business_line_from = _safe_int(col_k)
                rule.business_line_to = (
                    _safe_int(col_l) if col_l is not None else rule.business_line_from
                )

                self.rules.append(rule)

        wb.close()
        logger.info(f"Loaded {len(self.rules)} mapping rules from workbook")

    def map_tb_rows(self, tb_df: pd.DataFrame) -> pd.DataFrame:
        categories = []
        reasons = []
        unmapped = []
        mapped_count = 0

        # Fast dictionary records access (over 15x faster than tb_df.iterrows())
        records = tb_df.to_dict("records")
        for row_dict in records:
            matched_category, reason = self._find_category(row_dict)

            if matched_category:
                categories.append(matched_category)
                reasons.append("")
                mapped_count += 1
            else:
                categories.append("")
                reasons.append(reason)
                row_dict["unmapped_reason"] = reason
                unmapped.append(row_dict)

        tb_df = tb_df.copy()
        tb_df["revenue_category"] = categories
        tb_df["unmapped_reason"] = reasons

        self.unmapped_rows = unmapped
        self.unmapped_reasons = [r for r in reasons if r]
        logger.info(
            f"Mapping complete: {mapped_count} mapped, {len(unmapped)} unmapped out of {len(tb_df)} total"
        )

        return tb_df

    def _find_category(self, row: dict) -> Tuple[str, str]:
        flexfield = row.get("flexfield", "")
        segments = flexfield.split(".")
        if len(segments) < 9:
            return "", "Flexfield has fewer than 9 segments"

        cc = _safe_int(segments[1]) or 0
        bl = _safe_int(segments[3]) or 0
        prod = _safe_int(segments[4]) or 0
        acct = _safe_int(segments[5]) or 0
        tech = _safe_int(segments[6]) or 0

        matching_rules = [r for r in self.rules if r.matches(row)]

        if not matching_rules:
            # Fast hierarchical rule filtering instead of 3 full scans over all rules
            acct_rules = [
                r for r in self.rules
                if r.account_from is not None and r.account_from <= acct <= (r.account_to or r.account_from)
            ]
            if not acct_rules:
                return "", f"GL {acct} not covered by any rule range"

            prod_rules = [
                r for r in acct_rules
                if r.product_from is not None and r.product_from <= prod <= (r.product_to or r.product_from)
            ]
            if not prod_rules:
                return "", f"Product {prod} outside all rule ranges for GL {acct}"

            bl_rules = [
                r for r in prod_rules
                if r.business_line_from is not None and r.business_line_from <= bl <= (r.business_line_to or r.business_line_from)
            ]
            if not bl_rules:
                return (
                    "",
                    f"BL {bl} outside all rule ranges for GL {acct}, Product {prod}",
                )

            return (
                "",
                f"No rule matches GL {acct}, CC {cc}, Product {prod}, Tech {tech}, BL {bl}",
            )

        matching_rules.sort(key=lambda r: r.specificity_score(), reverse=True)
        best_match = matching_rules[0]
        category = _normalize_category(best_match.category)
        specificity = best_match.specificity_score()

        acct_segment = segments[5] if len(segments) > 5 else ""
        bl_segment = segments[3] if len(segments) > 3 else ""

        if category == "Equipment Sales":
            if not acct_segment.startswith("416"):
                return (
                    "",
                    f"Equipment Sales filter: Account {acct_segment} does not start with 416",
                )

        if category == "International" and specificity == 0:
            standard_intl_bls = {"83", "84", "86", "91", "92", "93"}
            if bl_segment not in standard_intl_bls:
                return (
                    "",
                    f"International filter: BL {bl_segment} not in standard international BLs",
                )

        return category, ""

    def get_unmapped_report(self) -> pd.DataFrame:
        if not self.unmapped_rows:
            return pd.DataFrame()
        return pd.DataFrame(self.unmapped_rows)

    def get_category_summary(self) -> Dict[str, int]:
        summary = {}
        for rule in self.rules:
            cat = rule.category
            if cat:
                summary[cat] = summary.get(cat, 0) + 1
        return summary


def _safe_int(value) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None" or text == "nan":
        return None
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None
