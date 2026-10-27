"""Hospital report-table adapters used internally by Report Decompose."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Iterable

from components.person_a.xlsx_reader import iter_xlsx_records


SUPPORTED_TABLE_TYPES = {"VGHTC2024", "CGMH2019"}
CGMH_REPORT_TEXT_FIELDS = ("pathology_report", "病理報告")
WSI_EXTENSIONS = (".ndpi", ".mrxs", ".svs", ".tif", ".tiff")
VGHTC_STAIN_CODES = {
    "H01": "HE",
    "G54": "ER",
    "G71": "HER2",
    "G7E": "KI67",
    "GAA": "PR",
}


@dataclass(frozen=True)
class ParsedReportTables:
    cases: list[dict[str, Any]]
    skipped_cases: list[dict[str, str]]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first(record: dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = _text(record.get(name))
        if value:
            return value
    return ""


def _normalize_stain(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", value.upper())
    aliases = {
        "HE": "HE",
        "H01": "HE",
        "HER2": "HER2",
        "HER2NEU": "HER2",
        "ER": "ER",
        "PR": "PR",
        "KI67": "KI67",
        "NC": "NC",
    }
    return aliases.get(compact, value.strip().upper() or "UNKNOWN")


def _new_case(case_id: str, hospital: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "hospital": hospital,
        "reports": [],
        "wsis": [],
        "observations": [],
        "_report_keys": set(),
        "_wsi_paths": set(),
        "_wsi_ids": set(),
        "_observation_keys": set(),
    }


def _case(
    cases: dict[str, dict[str, Any]], case_id: str, hospital: str
) -> dict[str, Any]:
    case = cases.setdefault(case_id, _new_case(case_id, hospital))
    if case["hospital"] != hospital:
        raise ValueError(
            f"Case {case_id!r} occurs in multiple hospitals: "
            f"{case['hospital']!r} and {hospital!r}"
        )
    return case


def _add_report(
    case: dict[str, Any], report_id: str, raw_text: str, table_idx: int, source: str
) -> None:
    if not raw_text:
        return
    key = (report_id, raw_text)
    if key in case["_report_keys"]:
        return
    case["_report_keys"].add(key)
    case["reports"].append(
        {
            "report_id": report_id or f"{case['case_id']}-report-{len(case['reports']) + 1:03d}",
            "raw_text": raw_text,
            "table_idx": table_idx,
            "source": source,
        }
    )


def _unique_wsi_id(case: dict[str, Any], requested: str) -> str:
    base = requested or f"{case['case_id']}-wsi-{len(case['wsis']) + 1:03d}"
    candidate = base
    suffix = 2
    while candidate in case["_wsi_ids"]:
        candidate = f"{base}-{suffix}"
        suffix += 1
    case["_wsi_ids"].add(candidate)
    return candidate


def _add_wsi(
    case: dict[str, Any], wsi_id: str, stain_type: str, wsi_path: str, block_id: str = ""
) -> None:
    if not wsi_path or wsi_path in case["_wsi_paths"]:
        return
    case["_wsi_paths"].add(wsi_path)
    case["wsis"].append(
        {
            "wsi_id": _unique_wsi_id(case, wsi_id),
            "stain_type": _normalize_stain(stain_type),
            "wsi_path": wsi_path,
            "block_id": block_id,
        }
    )


def _parse_reference_ids(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;|]", raw) if item.strip()]


def _add_observation(
    case: dict[str, Any], report_id: str, dx_item: str, dx_result: str, references: list[str]
) -> None:
    if not dx_item or not dx_result:
        return
    key = (report_id, dx_item, dx_result, tuple(references))
    if key in case["_observation_keys"]:
        return
    case["_observation_keys"].add(key)
    case["observations"].append(
        {
            "report_id": report_id,
            "dx_item": dx_item,
            "dx_result": dx_result,
            "reference_wsi_ids": references,
        }
    )


def _iter_combined_records(path: Path) -> Iterable[tuple[str, int, dict[str, str]]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row_number, record in enumerate(csv.DictReader(stream), start=2):
                yield path.name, row_number, dict(record)
        return
    if path.suffix.lower() == ".xlsx":
        yield from iter_xlsx_records(path)
        return
    raise ValueError(f"Unsupported report table file: {path}; expected .csv or .xlsx")


def _parse_combined_table(
    path: Path, table_idx: int, hospital: str, cases: dict[str, dict[str, Any]]
) -> None:
    for sheet_name, row_number, record in _iter_combined_records(path):
        case_id = _first(record, ["case_id", "Path_ID", "病理序號"])
        if not case_id:
            continue
        case = _case(cases, case_id, hospital)
        report_id = _first(record, ["report_id", "Path_ID", "病理序號"]) or case_id
        report_text = _first(record, ["report_text", "pathology_report", "病理報告"])
        source = f"{path.name}:{sheet_name}:{row_number}"
        _add_report(case, report_id, report_text, table_idx, source)

        wsi_path = _first(record, ["wsi_path", "image_path", "filepath"])
        wsi_id = _first(record, ["wsi_id", "WSI_name", "file_name"])
        _add_wsi(
            case,
            wsi_id or Path(wsi_path).stem,
            _first(record, ["stain_type", "stain"]),
            wsi_path,
            _first(record, ["block_id"]),
        )

        _add_observation(
            case,
            report_id,
            _first(record, ["dx_item"]),
            _first(record, ["dx_result"]),
            _parse_reference_ids(_first(record, ["reference_wsi_ids"])),
        )


def _read_data_paths(source_dir: Path) -> list[str]:
    path = source_dir / "data_path"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _filename_with_extension(filename: str, extension: str) -> str:
    if filename.lower().endswith(WSI_EXTENSIONS):
        return filename
    return f"{filename}{extension}"


def _without_wsi_extension(filename: str) -> str:
    """Remove a real slide-image extension without mistaking scan timestamps for one."""

    lowered = filename.lower()
    for extension in WSI_EXTENSIONS:
        if lowered.endswith(extension):
            return filename[: -len(extension)]
    return filename


def _portable_path(value: str) -> Path:
    """Interpret source-table path separators consistently on Linux containers."""

    return Path(value.replace("\\", "/"))


def _match_case_id(filename: str, case_ids: list[str]) -> tuple[str, str] | None:
    prefix = filename.split(",", 1)[0].strip()
    for case_id in case_ids:
        if prefix.startswith(case_id):
            block_id = prefix[len(case_id) :].strip().split("-", 1)[0]
            return case_id, block_id
    return None


def _slide_files(directory: Path) -> list[Path]:
    """Return only real WSI entry files, not MRXS companion data files."""

    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in WSI_EXTENSIONS
    )


def _vghtc_stain_from_filename(filename: str) -> str:
    stem = _without_wsi_extension(Path(filename).name)
    fields = [field.strip().upper() for field in stem.split(",")]
    return VGHTC_STAIN_CODES.get(fields[1], "UNKNOWN") if len(fields) > 1 else "UNKNOWN"


def _cgmh_case_aliases(case_id: str) -> list[str]:
    aliases = [case_id]
    match = re.fullmatch(r"S20(\d{2}-.*)", case_id, re.IGNORECASE)
    if match:
        aliases.append(f"S{match.group(1)}")
    return aliases


def _cgmh_stain_from_filename(filename: str) -> str:
    stem = _without_wsi_extension(Path(filename).name)
    if re.search(r"HER\s*[-_]?\s*2\s*(?:NEU)?", stem, re.IGNORECASE):
        return "HER2"
    if re.search(r"KI\s*[-_]?\s*67", stem, re.IGNORECASE):
        return "KI67"
    for marker in ("ER", "PR", "HE"):
        if re.search(rf"(?:^|[\s_-]){marker}(?:[\s_-]|$)", stem, re.IGNORECASE):
            return marker
    # Routine H&E slide names in the mounted CGMH sample do not always carry
    # an explicit "HE" token; named ER/PR/HER2/KI67 files are handled above.
    return "HE"


def _cgmh_filename_match(filename: str, case_id: str) -> tuple[str, str] | None:
    stem = _without_wsi_extension(Path(filename).name).strip()
    for alias in _cgmh_case_aliases(case_id):
        if not stem.casefold().startswith(alias.casefold()):
            continue
        remainder = stem[len(alias) :].strip()
        if not remainder:
            return stem, ""
        if _cgmh_stain_from_filename(stem) != "HE" or re.match(
            r"^HE(?:[\s_-]|$)", remainder, re.IGNORECASE
        ):
            return stem, ""
        block_id = re.split(r"[-\s_]", remainder, maxsplit=1)[0].strip()
        return stem, block_id
    return None


def _parse_vghtc_directory(
    source_dir: Path, table_idx: int, cases: dict[str, dict[str, Any]]
) -> None:
    source_case_ids: set[str] = set()
    report_paths = sorted(source_dir.glob("乳癌病理報告_*.xlsx"))
    for report_path in report_paths:
        for sheet_name, row_number, record in iter_xlsx_records(
            report_path, lambda name: "M85003" in name
        ):
            case_id = _first(record, ["病理序號"])
            report_text = _first(record, ["病理報告"])
            if case_id and report_text:
                source_case_ids.add(case_id)
                case = _case(cases, case_id, "VGHTC")
                _add_report(
                    case,
                    case_id,
                    report_text,
                    table_idx,
                    f"{report_path.name}:{sheet_name}:{row_number}",
                )

    case_ids = sorted(source_case_ids, key=len, reverse=True)
    data_paths = _read_data_paths(source_dir)
    base_root = Path(os.path.commonpath(data_paths)) if data_paths else source_dir
    wsi_table = source_dir / "VGHTC_list_total_2.xlsx"
    if wsi_table.is_file():
        for _, _, record in iter_xlsx_records(wsi_table):
            filename = _first(record, ["file_name"])
            match = _match_case_id(filename, case_ids)
            if not filename or match is None:
                continue
            case_id, block_id = match
            relative_dir = _first(record, ["file_path"])
            full_name = _filename_with_extension(filename, ".mrxs")
            directory = _portable_path(relative_dir)
            if not directory.is_absolute():
                directory = base_root / directory
            _add_wsi(
                cases[case_id],
                filename,
                _first(record, ["stain"]),
                str(directory / full_name),
                block_id,
            )
    else:
        for slide_path in _slide_files(source_dir / "中榮WSI"):
            filename = _without_wsi_extension(slide_path.name)
            match = _match_case_id(filename, case_ids)
            if match is None:
                continue
            case_id, block_id = match
            _add_wsi(
                cases[case_id],
                filename,
                _vghtc_stain_from_filename(filename),
                str(slide_path),
                block_id,
            )


def _parse_cgmh_directory(
    source_dir: Path, table_idx: int, cases: dict[str, dict[str, Any]]
) -> None:
    source_case_ids: set[str] = set()
    anonymous_directory_by_case: dict[str, str] = {}
    report_path = source_dir / "Pathology_Report_v1.xlsx"
    for sheet_name, row_number, record in iter_xlsx_records(report_path):
        case_id = _first(record, ["Path_ID"])
        # The real CGMH workbook uses the Chinese header.  Keep the English
        # alias for normalized/future exports while accepting the hospital file
        # without asking anyone to rename its columns.
        report_text = _first(record, CGMH_REPORT_TEXT_FIELDS)
        if case_id and report_text:
            source_case_ids.add(case_id)
            anonymous_directory = _first(record, ["anony_ID"])
            if anonymous_directory:
                anonymous_directory_by_case[case_id] = anonymous_directory
            case = _case(cases, case_id, "CGMH")
            _add_report(
                case,
                case_id,
                report_text,
                table_idx,
                f"{report_path.name}:{sheet_name}:{row_number}",
            )

    data_paths = _read_data_paths(source_dir)
    base_root = Path(data_paths[0]) if data_paths else source_dir

    stains_by_filename: dict[str, str] = {}
    wsi_table = source_dir / "CGMH_list_total.xlsx"
    if wsi_table.is_file():
        for _, _, record in iter_xlsx_records(wsi_table):
            filename = _without_wsi_extension(_first(record, ["file_name"])).strip()
            if filename:
                stains_by_filename[filename] = _first(record, ["stain"])

    image_table = source_dir / "Pathology_image_path_v1.csv"
    if image_table.is_file():
        with image_table.open("r", encoding="utf-8-sig", newline="") as stream:
            records = csv.DictReader(stream)
            for record in records:
                case_id = _first(record, ["Path_ID"])
                if case_id not in source_case_ids:
                    continue
                filename = _first(record, ["WSI_name"])
                if not filename:
                    continue
                # The CGMH codebook defines the on-disk layout as
                # <data_path>/<anony_ID>/<WSI_name>.  ``image_path`` is a Windows-style
                # legacy location and must not be appended to the Linux mount path.
                relative_dir = _first(record, ["anony_ID"])
                if not relative_dir:
                    relative_dir = _portable_path(_first(record, ["image_path"])).name
                directory = _portable_path(relative_dir)
                if not directory.is_absolute():
                    directory = base_root / directory
                filename_key = _without_wsi_extension(filename).strip()
                block_id = filename_key[len(case_id) :].strip().split("-", 1)[0]
                _add_wsi(
                    cases[case_id],
                    filename_key,
                    stains_by_filename.get(filename_key, "UNKNOWN"),
                    str(directory / filename),
                    block_id,
                )
    else:
        for case_id, anonymous_directory in anonymous_directory_by_case.items():
            for slide_path in _slide_files(source_dir / anonymous_directory):
                match = _cgmh_filename_match(slide_path.name, case_id)
                if match is None:
                    continue
                filename_key, block_id = match
                _add_wsi(
                    cases[case_id],
                    filename_key,
                    _cgmh_stain_from_filename(filename_key),
                    str(slide_path),
                    block_id,
                )


def _finalize_cases(cases: dict[str, dict[str, Any]]) -> ParsedReportTables:
    finalized: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for case_id in sorted(cases):
        case = cases[case_id]
        if not case["reports"]:
            skipped.append({"case_id": case_id, "reason": "missing report"})
            continue
        if not case["wsis"]:
            skipped.append({"case_id": case_id, "reason": "missing WSI"})
            continue

        wsi_ids = [wsi["wsi_id"] for wsi in case["wsis"]]
        dx_pairs = []
        for index, observation in enumerate(case["observations"], start=1):
            references = observation["reference_wsi_ids"]
            unknown = sorted(set(references) - set(wsi_ids))
            if unknown:
                raise ValueError(
                    f"Case {case_id!r} DxPair references unknown WSI IDs: {unknown!r}"
                )
            dx_pairs.append(
                {
                    "dx_pair_id": f"{case_id}-dx-{index:03d}",
                    "case_id": case_id,
                    "source_report_id": observation["report_id"],
                    "dx_item": observation["dx_item"],
                    "dx_result": observation["dx_result"],
                    "reference_wsi_ids": references,
                }
            )

        finalized.append(
            {
                "case_id": case_id,
                "hospital": case["hospital"],
                "reports": case["reports"],
                "wsis": sorted(case["wsis"], key=lambda item: item["wsi_id"]),
                "dx_pairs": dx_pairs,
            }
        )
    return ParsedReportTables(cases=finalized, skipped_cases=skipped)


def parse_report_tables(
    tables: list[dict[str, Any]], manifest_directory: str | Path
) -> ParsedReportTables:
    cases: dict[str, dict[str, Any]] = {}
    seen_indexes: set[int] = set()
    base = Path(manifest_directory)

    for table in sorted(tables, key=lambda item: item["table_idx"]):
        table_idx = table["table_idx"]
        if table_idx in seen_indexes:
            raise ValueError(f"Duplicate table_idx: {table_idx}")
        seen_indexes.add(table_idx)

        table_type = table["table_type"]
        if table_type not in SUPPORTED_TABLE_TYPES:
            raise ValueError(f"Unsupported table_type: {table_type!r}")
        source = Path(table["table_path"])
        if not source.is_absolute():
            source = (base / source).resolve()
        if not source.exists():
            raise FileNotFoundError(f"Report table source does not exist: {source}")

        if source.is_dir() and table_type == "VGHTC2024":
            _parse_vghtc_directory(source, table_idx, cases)
        elif source.is_dir() and table_type == "CGMH2019":
            _parse_cgmh_directory(source, table_idx, cases)
        else:
            hospital = "VGHTC" if table_type == "VGHTC2024" else "CGMH"
            _parse_combined_table(source, table_idx, hospital, cases)

    return _finalize_cases(cases)
