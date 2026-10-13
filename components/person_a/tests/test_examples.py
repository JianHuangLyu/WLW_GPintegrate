from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from components.person_a.query_generation import build_example_artifact
from components.person_a.report_decompose import build_artifact
from contracts.runtime import ContractError, validate_artifact, validate_case_list_input
from contracts.paths import RUN_ROOT


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
EXAMPLE_CONFIG = ROOT / "configs/example.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PersonAExampleTests(unittest.TestCase):
    def test_report_decompose_canonical_example(self) -> None:
        directory = ROOT / "examples/report_decompose"
        source = _json(directory / "case_list.valid.json")
        config = _json(EXAMPLE_CONFIG)
        expected = _json(directory / "D_dx_pairs.expected.json")
        validate_case_list_input(source, single_case=True)
        actual = build_artifact(source, config)
        validate_artifact(actual, "D.DxPairs")
        self.assertEqual(expected, actual)

    def test_invalid_case_list_fails(self) -> None:
        source = _json(
            ROOT / "examples/report_decompose/case_list.invalid.json"
        )
        with self.assertRaises(ContractError):
            validate_case_list_input(source, single_case=True)

    def test_query_generation_canonical_example(self) -> None:
        directory = ROOT / "examples/query_generation"
        d_artifact = _json(directory / "D_dx_pairs.valid.json")
        f_artifact = _json(directory / "F_chunks.valid.json")
        config = _json(EXAMPLE_CONFIG)
        expected = _json(directory / "G_queries.expected.json")
        validate_artifact(d_artifact, "D.DxPairs")
        validate_artifact(f_artifact, "F.Chunks")
        actual = build_example_artifact(
            d_artifact, f_artifact, config["component_version"]
        )
        validate_artifact(actual, "G.VisualAttributeQueries")
        self.assertEqual(expected, actual)

    def _run_cli(
        self,
        module: str,
        inputs: list[Path],
        output: Path,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-m", module]
        for input_path in inputs:
            command.extend(["--input", str(input_path)])
        command.extend(
            ["--output", str(output), "--config", str(EXAMPLE_CONFIG)]
        )
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_report_decompose_canonical_cli(self) -> None:
        directory = ROOT / "examples/report_decompose"
        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as temp_dir:
            runtime = Path(temp_dir)
            source = runtime / "case_list.valid.json"
            output = runtime / "D_dx_pairs.json"
            shutil.copyfile(directory / "case_list.valid.json", source)

            result = self._run_cli(
                "components.person_a.report_decompose", [source], output
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                _json(directory / "D_dx_pairs.expected.json"),
                _json(output),
            )

    def test_query_generation_canonical_cli_accepts_both_input_orders(self) -> None:
        directory = ROOT / "examples/query_generation"
        expected = _json(directory / "G_queries.expected.json")
        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as temp_dir:
            runtime = Path(temp_dir)
            d_path = runtime / "D_dx_pairs.valid.json"
            f_path = runtime / "F_chunks.valid.json"
            shutil.copyfile(directory / "D_dx_pairs.valid.json", d_path)
            shutil.copyfile(directory / "F_chunks.valid.json", f_path)

            for index, inputs in enumerate(([d_path, f_path], [f_path, d_path])):
                output = runtime / f"G_queries-{index}.json"
                result = self._run_cli(
                    "components.person_a.query_generation", list(inputs), output
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(expected, _json(output))

    def test_invalid_report_cli_leaves_no_partial_output(self) -> None:
        directory = ROOT / "examples/report_decompose"
        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as temp_dir:
            runtime = Path(temp_dir)
            source = runtime / "case_list.invalid.json"
            output = runtime / "D_dx_pairs.json"
            shutil.copyfile(directory / "case_list.invalid.json", source)

            result = self._run_cli(
                "components.person_a.report_decompose", [source], output
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
