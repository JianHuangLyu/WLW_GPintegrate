"""Reusable report-text extraction boundary for Report Decompose.

The original Query_Design scripts read whole Excel workbooks and wrote their
own JSON files.  In the integrated pipeline, ``table_parsers`` owns workbook
I/O and this module only receives one normalized case at a time.  That keeps
the extraction logic reusable for CSV fixtures, raw hospital directories and
future server-side table sources.
"""

from __future__ import annotations

import re
import json
import logging
from typing import Any

from components.person_a.histologic_type_classifier import classify_histologic_type


# Keep the two Query_Design regex implementations separate. Their aliases and
# stop conditions are hospital-specific and must not be silently unified.
VGHTC_ITEM_ALIASES: dict[str, list[str]] = {
    "Histologic Type": ["Histologic Type"],
    "Histologic Grade": ["Histologic Grade"],
    "size of invasive carcinoma": [
        "size of invasive carcinoma",
        "The largest size of invasive carcinoma",
    ],
    "Angiolymphatic permeation": ["Angiolymphatic permeation"],
    "Perineural invasion": ["Perineural invasion"],
    "Tumor focality": ["Tumor focality"],
    "Margins": ["Margins"],
    "Microcalcification": ["Microcalcification", "Microcalcifications"],
    "Lymph node status": ["Lymph node status"],
    "Extranodal involvement": ["Extranodal involvement"],
    "Architectural pattern of DCIS": ["Architectural pattern of DCIS"],
    "Nuclear grade of DCIS": ["Nuclear grade of DCIS"],
    "Necrosis of DCIS": ["Necrosis of DCIS"],
    "Extensive intraductal component": ["Extensive intraductal component"],
    "ER status": ["ER status", "Estrogen receptor"],
    "PR status": ["PR status", "Progesterone receptor"],
    "Her-2/neu status": ["Her-2/neu status"],
    "Ki-67 labeling index": ["Ki-67 labeling index"],
    "Treatment Effect": ["Treatment Effect"],
    "pT Category": ["pT Category"],
    "pN Category": ["pN Category"],
    "pM Category": ["pM Category"],
    "Pathological TNM stage": ["Pathological TNM stage"],
    "TNM descriptors": ["TNM descriptors"],
}


CGMH_ITEM_ALIASES: dict[str, list[str]] = {
    "Histologic Type": [
        "Histologic Type",
        "The invasive carcinoma is",
        "Invasive Carcinoma",
        "The tumor is",
        "The tumor cells are",
        "The invasive carcinoma tumor cells are",
    ],
    "Histologic Grade": [
        "Histologic Grade",
        "Nottingham Histologic Score",
        "Grade",
    ],
    "size of invasive carcinoma": [
        "size of invasive carcinoma",
        "The largest size of invasive carcinoma",
        "Tumor Size",
    ],
    "Angiolymphatic permeation": [
        "Angiolymphatic permeation",
        "Lymphovascular Invasion",
        "Angiolymphatic invasion",
    ],
    "Perineural invasion": ["Perineural invasion"],
    "Tumor focality": ["Tumor focality"],
    "Tumor infiltrating lymphocytes (TILs)": [
        r"Tumor infiltrating lymphocytes \(TILs\)",
        "Tumor infiltrating lymphocytes",
        "TILs",
        "TIL",
    ],
    "Margins": ["Margins", "Margin"],
    "Microcalcification": [
        "Microcalcification",
        "Microcalcifications",
        "Calcification",
        "Calcifications",
    ],
    "Lymph node status": ["Lymph node status", "Regional Lymph Nodes"],
    "Extranodal involvement": ["Extranodal involvement"],
    "Architectural pattern of DCIS": [
        "Architectural pattern of DCIS",
        "Architectural Patterns",
    ],
    "Nuclear grade of DCIS": ["Nuclear grade of DCIS", "Nuclear Grade"],
    "Necrosis of DCIS": ["Necrosis of DCIS", "Necrosis", "Comedo necrosis"],
    "Extensive intraductal component": ["Extensive intraductal component"],
    "ER status": [
        "ER status",
        "Estrogen receptor",
        r"ER\(6F11\)",
        r"ER\(6F11/Novacastra\)",
    ],
    "PR status": [
        "PR status",
        "Progesterone receptor",
        r"PR\(1A6\)",
        r"PR\(1A6/Novacastra\)",
    ],
    "Her-2/neu status": [
        "Her-2/neu status",
        r"HER-2-neu\(polyclone\)",
        "HER2",
        r"HER-2-neu\(polyclone/DAKO\)",
        "Her-2/neu",
    ],
    "Ki-67 labeling index": [
        "Ki-67 labeling index",
        r"Ki-67\(MIB-1\)",
        "Ki-67",
        "KI067",
        r"The ki-67\(MIB-1\) index is",
        r"Ki-67\(MIB-1\) labeling index",
    ],
    "Treatment Effect": ["Treatment Effect"],
    "pT Category": ["pT Category"],
    "pN Category": ["pN Category"],
    "pM Category": ["pM Category"],
    "Pathological TNM stage": ["Pathological TNM stage", "TNM stage"],
    "TNM descriptors": ["TNM descriptors"],
}


GROSS_STOP_RE = re.compile(r"\bGross\s*description\s*[:：]", re.IGNORECASE)
CGMH_GRADE_SUB_ITEMS = [
    "Tubular Differentiation",
    "Ductal formation",
    "Nuclear Pleomorphism",
    "Mitotic Rate",
    "Mitotic count",
    "Overall Score",
    "Overall Grade",
    "Overall Tentative Grade",
    "Tentative Overall Grade",
]
CGMH_EXTRA_STOP_LABELS = [
    "CK14",
    "P63",
    "p63/CK14",
    "CK14 and P63",
    "E-cadherin",
    "p120",
    "CK5/6",
    "Synaptophysin",
    "Chromogranin",
    "GATA3",
    "Calponin",
    "SMA",
    "CD31",
    "D2-40",
    "Ductal Carcinoma In Situ (DCIS)",
]
CGMH_DOT_SPACE_DASH_STOP = r"\.\s+-\s+"
_cgmh_stop_labels = [
    alias.replace("\\", "")
    for aliases in CGMH_ITEM_ALIASES.values()
    for alias in aliases
]
_cgmh_stop_labels.extend(CGMH_GRADE_SUB_ITEMS)
_cgmh_stop_labels.extend(CGMH_EXTRA_STOP_LABELS)
_cgmh_stop_labels.extend(
    ["DX", "GROSS D", "MICRO D", "ADDENDUM", "Description", "Disclaimer", "Note", "SNOMED"]
)
CGMH_STOP_PATTERN = "|".join(
    re.escape(label)
    for label in sorted(set(_cgmh_stop_labels), key=len, reverse=True)
)


def _key(value: str) -> str:
    """Normalize a label/result for safe case-insensitive matching."""

    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _clean_value(value: str) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if compact.casefold() in {
        "",
        "na",
        "n/a",
        "none",
        "null",
        "not mentioned",
        "not specified",
        "not found",
    }:
        return ""
    return compact


def _vghtc_alias_expression(alias: str) -> str:
    escaped = re.escape(alias)
    escaped = escaped.replace(r"\ ", r"\s*")
    escaped = escaped.replace(r"\-", r"\s*[-\s]*\s*")
    escaped = escaped.replace(r"\/", r"\s*[/\s]*\s*")
    return escaped


def extract_vghtc_items(report_text: str) -> dict[str, str]:
    """Run the regex generation and Gross-description stop from De中榮.py."""
    if not report_text:
        return {}
    gross = GROSS_STOP_RE.search(report_text)
    text = report_text[: gross.start()] if gross else report_text

    extracted: dict[str, str] = {}
    for item_name, aliases in VGHTC_ITEM_ALIASES.items():
        patterns = [
            rf"(?:\d+\.\s*)?{_vghtc_alias_expression(alias)}"
            rf"(?:\s*\(.*?\))?\s*[:：]\s*(.*?)(?=\n\d+\.|\Z)"
            for alias in aliases
        ]
        pattern = re.compile("|".join(patterns), re.IGNORECASE | re.DOTALL)
        match = pattern.search(text)
        if match:
            raw_value = next(
                (group for group in match.groups() if group is not None), ""
            ).strip()
            value = re.sub(r"\s+", " ", raw_value).strip()
            if value and value.casefold() != "not found":
                extracted[item_name] = value
    return extracted


def _cgmh_post_clean(value: str) -> str:
    if not value:
        return value
    cleaned = re.sub(r"\s+", " ", value).strip()
    cleaned = re.split(CGMH_DOT_SPACE_DASH_STOP, cleaned, maxsplit=1)[0].strip()
    return re.sub(r"[\s\.\:\：\-]+$", "", cleaned).strip()


def extract_cgmh_items(report_text: str) -> dict[str, str]:
    """Run the stop-label and grade-subitem regex flow from De長庚.py."""
    if not report_text:
        return {}

    extracted: dict[str, str] = {}
    for item_name, aliases in CGMH_ITEM_ALIASES.items():
        if item_name == "Histologic Grade":
            continue
        for alias in aliases:
            pattern = (
                rf"{alias}\s*[:：]\s*(.*?)"
                rf"(?=\s*[\.\u2026;；,，]*\s*(?:{CGMH_STOP_PATTERN})\s*[:：]"
                rf"|\.\s+[A-Z]|{CGMH_DOT_SPACE_DASH_STOP}|\n\d+\.|\Z)"
            )
            match = re.search(pattern, report_text, re.IGNORECASE | re.DOTALL)
            if match:
                value = _cgmh_post_clean(match.group(1))
                if value and value.casefold() != "not found":
                    extracted[item_name] = value
                    break

    grade_parts = []
    for sub_item in CGMH_GRADE_SUB_ITEMS:
        pattern = (
            rf"{re.escape(sub_item)}\s*[:：]\s*(.*?)"
            rf"(?=\s+(?:{CGMH_STOP_PATTERN})\s*[:：]"
            rf"|{CGMH_DOT_SPACE_DASH_STOP}|\n\d+\.|\Z)"
        )
        match = re.search(pattern, report_text, re.IGNORECASE | re.DOTALL)
        if match:
            value = _cgmh_post_clean(match.group(1))
            if value:
                grade_parts.append(f"{sub_item}: {value}")
    if grade_parts:
        extracted["Histologic Grade"] = ". ".join(grade_parts) + "."
    return extracted


def extract_labeled_items(report_text: str) -> dict[str, str]:
    """Backward-compatible name for the original VGHTC regex extractor."""
    return extract_vghtc_items(report_text)


class ReportExtractionEngine:
    """Turn normalized case reports into the DxPairs consumed by D.DxPairs."""

    def __init__(self, catalog: dict[str, Any], config: dict[str, Any] | None = None):
        self.catalog = catalog
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.backend = self.config.get("backend", "hospital_routed")
        if self.backend not in {
            "hospital_routed",
            "regex",
            "medgemma",
            "regex_then_medgemma",
        }:
            raise ValueError(f"Unsupported report extraction backend: {self.backend!r}")
        self.only_when_missing = bool(self.config.get("only_when_missing", True))
        self.strict_result_classes = bool(
            self.config.get("strict_result_classes", True)
        )
        self._catalog_by_key = {_key(name): name for name in catalog}
        self._medgemma: Any | None = None
        self.provenance: dict[str, Any] = {}
        self._audit_context: dict[str, str] = {}

        configured_names = self.config.get("item_name_map", {})
        self.item_name_map: dict[str, str] = {}
        for source_name, target_name in configured_names.items():
            if target_name not in catalog:
                raise ValueError(
                    f"report_extraction.item_name_map target {target_name!r} "
                    "is not present in DxStructuredCandidates_integrated.json"
                )
            self.item_name_map[_key(source_name)] = target_name

    def _audit(self, event: str, **details: Any) -> None:
        # Record routing and counts, never report text, generated text or credentials.
        logging.getLogger(__name__).info(json.dumps(
            {"event": event, **self._audit_context, **details}, ensure_ascii=True
        ))

    def _catalog_name(self, extracted_name: str) -> str | None:
        normalized = _key(extracted_name)
        if normalized in self.item_name_map:
            return self.item_name_map[normalized]
        return self._catalog_by_key.get(normalized)

    def _medgemma_items(self) -> list[str]:
        configured = self.config.get("medgemma", {}).get("items")
        if configured is None:
            return list(self.catalog)
        resolved = []
        for item in configured:
            name = self._catalog_name(item)
            if name is None:
                raise ValueError(f"Unknown MedGemma extraction item: {item!r}")
            resolved.append(name)
        return resolved

    def _medgemma_extract(
        self, report_text: str, items: list[str] | None = None
    ) -> dict[str, str]:
        if self._medgemma is None:
            from components.person_a.medgemma_extractor import MedGemmaExtractor

            self._medgemma = MedGemmaExtractor(self.config.get("medgemma", {}))
        requested = items or self._medgemma_items()
        before = getattr(self._medgemma, "generation_count", 0)
        self._audit("medgemma_start", items=requested)
        result = self._medgemma.extract(report_text, requested)
        model_provenance = getattr(self._medgemma, "provenance", None)
        if model_provenance:
            self.provenance["medgemma_report_extraction"] = model_provenance
        self._audit(
            "medgemma_complete", items=requested,
            nonempty_items=[key for key, value in result.items() if value],
            generate_calls=getattr(self._medgemma, "generation_count", 0) - before,
        )
        return result

    def _extract_cgmh_report(self, report_text: str) -> dict[str, str]:
        """Implement the confirmed CGMH fallback flow.

        - Regex found nothing: ask MedGemma for the complete configured item set.
        - Regex found anything: keep those values and ask MedGemma only for
          Histologic Type.  A non-empty model Histologic Type replaces the
          regex Histologic Type while every other regex value is preserved.
        """

        regex_items = extract_cgmh_items(report_text)
        self._audit("regex_complete", hospital="CGMH", items=list(regex_items))
        if not regex_items:
            return self._medgemma_extract(report_text)

        histologic_item = self._catalog_name("Histologic Type")
        if histologic_item is None:
            return regex_items
        model_histologic = self._medgemma_extract(report_text, [histologic_item])
        histologic_value = model_histologic.get(histologic_item)
        if not histologic_value:
            return regex_items

        merged = {
            item_name: value
            for item_name, value in regex_items.items()
            if self._catalog_name(item_name) != histologic_item
        }
        merged[histologic_item] = histologic_value
        return merged

    def _extract_report(self, report_text: str, hospital: str) -> dict[str, str]:
        if self.backend == "hospital_routed":
            if hospital == "VGHTC":
                # VGHTC is deliberately regex-only.  Never load MedGemma here.
                result = extract_vghtc_items(report_text)
                self._audit("regex_complete", hospital="VGHTC", items=list(result))
                return result
            if hospital == "CGMH":
                return self._extract_cgmh_report(report_text)
            raise ValueError(f"Unsupported hospital for report extraction: {hospital!r}")

        regex_items = extract_vghtc_items(report_text) if self.backend != "medgemma" else {}
        if self.backend == "regex":
            return regex_items
        if self.backend == "medgemma":
            return self._medgemma_extract(report_text)

        # Hybrid mode keeps deterministic regex hits and asks the model only
        # for items that are still missing.
        regex_catalog_names = {
            catalog_name
            for item_name in regex_items
            if (catalog_name := self._catalog_name(item_name)) is not None
        }
        missing = [
            item for item in self._medgemma_items() if item not in regex_catalog_names
        ]
        model_items = self._medgemma_extract(report_text, missing) if missing else {}
        for item_name, value in model_items.items():
            regex_items.setdefault(item_name, value)
        return regex_items

    def _mapped_result_class(self, item_name: str, raw_value: str) -> str:
        definition = self.catalog[item_name]
        allowed = definition.get("DxResultCls", [])

        configured = self.config.get("result_class_map", {}).get(item_name, {})
        configured_by_key = {_key(source): target for source, target in configured.items()}
        result_class = configured_by_key.get(_key(raw_value), raw_value)

        allowed_by_key = {
            _key(value): value for value in allowed if isinstance(value, str)
        }
        canonical = allowed_by_key.get(_key(result_class))
        if canonical is not None:
            return canonical

        if _key(item_name) == _key("Histologic_Type"):
            classified = classify_histologic_type(raw_value)
            canonical = allowed_by_key.get(_key(classified))
            if canonical is not None:
                return canonical

        # An empty candidate list means this DxItem is intentionally free text.
        # Only items with declared classes are restricted by strict mode.
        if self.strict_result_classes and allowed:
            raise ValueError(
                f"Extracted {item_name} result {raw_value!r} is not one of the "
                "DxStructuredCandidates_integrated.json classes; add a "
                "report_extraction.result_class_map entry"
            )
        return result_class

    def fill_case(self, case: dict[str, Any]) -> dict[str, Any]:
        """Populate ``case['dx_pairs']`` when hospital tables did not provide it."""

        if not self.enabled:
            return case
        if case["dx_pairs"] and self.only_when_missing:
            # Pre-structured fixtures/tables may carry raw Histologic Type text.
            # Normalize that one classified item while leaving already-valid
            # classes and all free-text items untouched.
            for pair in case["dx_pairs"]:
                item_name = pair["dx_item"]
                if item_name not in self.catalog:
                    continue
                raw_value = pair["dx_result"]
                result_class = self._mapped_result_class(item_name, raw_value)
                if result_class != raw_value:
                    pair["dx_result"] = result_class
                    pair.setdefault("dx_result_text", raw_value)
                    pair.setdefault("dx_result_raw_text", raw_value)
            return case

        extracted_by_item: dict[str, dict[str, str]] = {}
        for report in case["reports"]:
            self._audit_context = {
                "case_id": case["case_id"],
                "report_id": report["report_id"],
                "hospital": case.get("hospital", ""),
            }
            self._audit("report_extraction_start", backend=self.backend)
            for extracted_name, raw_value in self._extract_report(
                report["raw_text"], case.get("hospital", "")
            ).items():
                item_name = self._catalog_name(extracted_name)
                if item_name is None or item_name in extracted_by_item:
                    continue
                cleaned = _clean_value(raw_value)
                if cleaned:
                    extracted_by_item[item_name] = {
                        "report_id": report["report_id"],
                        "raw_value": cleaned,
                    }

        pairs = list(case["dx_pairs"]) if not self.only_when_missing else []
        used_items = {pair["dx_item"] for pair in pairs}
        for item_name, extracted in extracted_by_item.items():
            if item_name in used_items:
                continue
            pair_number = len(pairs) + 1
            raw_value = extracted["raw_value"]
            pairs.append(
                {
                    "dx_pair_id": f"{case['case_id']}-dx-{pair_number:03d}",
                    "case_id": case["case_id"],
                    "source_report_id": extracted["report_id"],
                    "dx_item": item_name,
                    "dx_result": self._mapped_result_class(item_name, raw_value),
                    "dx_result_text": raw_value,
                    "dx_result_raw_text": raw_value,
                    "reference_wsi_ids": [],
                }
            )
            used_items.add(item_name)
        case["dx_pairs"] = pairs
        return case
