"""Seven-class Histologic Type normalization from Query_Design.

The raw extracted diagnosis is kept separately as DxResultTxt.  This module
only produces the agreed DxResultCls value.
"""

from __future__ import annotations

import re


HISTOLOGIC_TYPE_CLASSES = (
    "UDH",
    "FEA",
    "ADH",
    "DCIS",
    "IC",
    "OTHER",
    "AMBIGUOUS",
)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def classify_histologic_type(value: str) -> str:
    """Classify raw Histologic Type text using the original seven-class rules."""

    text = _clean_text(value)
    if not text:
        return ""

    if text in {
        "breast",
        "skin",
        "lymph node",
        "breast, left, core needle biopsy",
        "breast, right, core needle biopsy",
        "benign",
    }:
        return "OTHER"
    if any(term in text for term in ("e-cadherin", "all tumor cells negative")):
        return "OTHER"

    if "flat epithelial atypia" in text:
        return "FEA"
    if (
        "atypical ductal hyperplasia" in text
        or "atypical intraductal hyperplasia" in text
    ):
        return "ADH"
    if "usual ductal hyperplasia" in text:
        return "UDH"
    if (
        ("ductal hyperplasia" in text or "intraductal hyperplasia" in text)
        and "atypical" not in text
        and "atypia" not in text
        and "carcinoma" not in text
    ):
        return "UDH"

    other_terms = (
        "fibroadenoma",
        "fibroadenomatous hyperplasia",
        "fibroepithelial lesion",
        "fibrocystic change",
        "fibrocystic disease",
        "adenosis",
        "sclerosing adenosis",
        "microglandular adenosis",
        "tubular adenoma",
        "biphasic neoplasm",
        "atypical epithelioid spindle cell neoplasm",
        "papillary neoplasm",
        "intraductal papillary neoplasm",
        "lobular carcinoma in situ",
        "atypical lobular hyperplasia",
    )
    if any(term in text for term in other_terms):
        if "invasive" not in text and "microinvasive" not in text:
            return "OTHER"

    invasive_terms = (
        "invasive",
        "infiltrating",
        "microinvasive",
        "mucinous carcinoma",
        "lobular carcinoma",
        "metaplastic carcinoma",
        "neuroendocrine carcinoma",
        "small cell",
        "signet ring cell carcinoma",
        "medullary carcinoma",
        "adenoid cystic carcinoma",
        "adenocarcinoma",
    )
    if any(term in text for term in invasive_terms):
        return "IC"

    in_situ_terms = (
        "ductal carcinoma in situ",
        "dcis",
        "intraductal carcinoma",
        "papillary ductal carcinoma in situ",
        "high grade ductal carcinoma in situ",
        "carcinoma in situ",
    )
    if any(term in text for term in in_situ_terms):
        return "DCIS"

    if any(
        term in text
        for term in ("ductal carcinoma", "carcinoma", "papillary carcinoma")
    ):
        return "AMBIGUOUS"
    return "AMBIGUOUS"
