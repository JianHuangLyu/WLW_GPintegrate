from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from components.person_a.reference_data import (
    load_histologic_mapping,
    load_visual_references,
)
from contracts.paths import REFERENCE_ROOT


PERSON_A_REFERENCE = REFERENCE_ROOT / "person_a/template_ref"


class ReferenceDataTests(unittest.TestCase):
    def test_mapping_is_loaded_from_the_configured_file_at_runtime(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            path = Path(temp_dir) / "mapping.json"
            path.write_text(
                json.dumps({"Histologic_Type_mappingTable": {"Custom": "Target"}}),
                encoding="utf-8",
            )
            mapping, provenance = load_histologic_mapping(
                path, integrity_mode="record_only"
            )
            self.assertEqual({"Custom": "Target"}, mapping)
            self.assertEqual("mapping.json", provenance["source_name"])
            self.assertEqual("record_only", provenance["integrity_mode"])

    def test_type_level_filename_revision_and_polarity_are_canonicalized(self) -> None:
        candidate_path = PERSON_A_REFERENCE / "candidateReference.json"
        type_level_path = (
            PERSON_A_REFERENCE / "[typeLevel]visualAttrs_v1.2.1_2603241656.json"
        )
        _, type_levels, provenance = load_visual_references(
            candidate_path, type_level_path
        )
        self.assertTrue(
            provenance["candidate_reference"]["integrity_verified"]
        )
        self.assertTrue(
            provenance["type_level_visual_attrs"]["integrity_verified"]
        )
        self.assertTrue(type_levels)
        self.assertTrue(all(item["version"] == "1.2.1" for item in type_levels))
        self.assertTrue(
            all(
                item["visualAttrs"]["Cellular_and_Nuclear"]["Polarity"]["type"]
                == "ordinal"
                for item in type_levels
            )
        )


if __name__ == "__main__":
    unittest.main()
