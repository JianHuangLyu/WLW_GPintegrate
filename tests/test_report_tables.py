from __future__ import annotations

import unittest

from components.person_a.table_parsers import (
    CGMH_REPORT_TEXT_FIELDS,
    _cgmh_case_aliases,
    _cgmh_filename_match,
    _cgmh_stain_from_filename,
    _first,
    _filename_with_extension,
    _portable_path,
    _vghtc_stain_from_filename,
    _without_wsi_extension,
)


class ReportTableParserTests(unittest.TestCase):
    def test_cgmh_accepts_the_real_chinese_report_header(self) -> None:
        self.assertEqual(
            "real report text",
            _first({"病理報告": "real report text"}, CGMH_REPORT_TEXT_FIELDS),
        )

    def test_known_wsi_extension_does_not_consume_scan_timestamp(self) -> None:
        filename = "slide-name_15.33.07.ndpi"
        self.assertEqual("slide-name_15.33.07", _without_wsi_extension(filename))
        self.assertEqual("slide-name_15.33.07", _without_wsi_extension(filename[:-5]))
        self.assertEqual(
            "slide-name_15.33.07.mrxs",
            _filename_with_extension("slide-name_15.33.07", ".mrxs"),
        )

    def test_windows_source_directory_is_portable(self) -> None:
        self.assertEqual("batch/patient", _portable_path("batch\\patient").as_posix())

    def test_vghtc_mounted_wsi_filename_supplies_stain(self) -> None:
        self.assertEqual("HE", _vghtc_stain_from_filename("S1300917D,H01,130109.mrxs"))
        self.assertEqual("ER", _vghtc_stain_from_filename("S1300917D,G54,130115.mrxs"))
        self.assertEqual("HER2", _vghtc_stain_from_filename("S1300917D,G71,130115.mrxs"))
        self.assertEqual("KI67", _vghtc_stain_from_filename("S1300917D,G7E,130115.mrxs"))
        self.assertEqual("PR", _vghtc_stain_from_filename("S1300917D,GAA,130115.mrxs"))

    def test_cgmh_mounted_wsi_filename_supplies_stain_and_case_alias(self) -> None:
        self.assertEqual(["S2019-047744", "S19-047744"], _cgmh_case_aliases("S2019-047744"))
        self.assertEqual("HE", _cgmh_stain_from_filename("S19-047744 HE _23.53.31.ndpi"))
        self.assertEqual("ER", _cgmh_stain_from_filename("S2019-047744 ER _14.17.11.ndpi"))
        self.assertEqual("HER2", _cgmh_stain_from_filename("S2019-047744 Her-2neu _14.22.34.ndpi"))
        self.assertEqual("KI67", _cgmh_stain_from_filename("S2019-047744 Ki-67 _14.24.41.ndpi"))
        self.assertEqual("PR", _cgmh_stain_from_filename("S2019-047744 PR _14.18.44.ndpi"))
        self.assertEqual(
            ("S19-047744 HE _23.53.31", ""),
            _cgmh_filename_match("S19-047744 HE _23.53.31.ndpi", "S2019-047744"),
        )
        self.assertEqual(
            ("S2019-047744A-001                _21.56.06", "A"),
            _cgmh_filename_match(
                "S2019-047744A-001                _21.56.06.ndpi", "S2019-047744"
            ),
        )


if __name__ == "__main__":
    unittest.main()
