from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_law_lens.current_case import (
    CurrentCaseError,
    case_number_from_case_dir,
    clean_case_name,
    current_case_socf,
    current_case_socf_odt,
    find_socf_odt,
    resolve_case_dir,
)


class CurrentCaseTests(unittest.TestCase):
    def test_clean_case_name_rejects_empty_and_path_values(self) -> None:
        with self.assertRaises(CurrentCaseError):
            clean_case_name("   ")
        with self.assertRaises(CurrentCaseError):
            clean_case_name("../B123456_Test")

    def test_resolve_case_dir_checks_open_and_closed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_name = "B123456_Test_Case"
            closed_case = root / "CLOSED_CASES" / case_name
            closed_case.mkdir(parents=True)

            self.assertEqual(
                resolve_case_dir(case_name, [root / "OPEN_CASES", root / "CLOSED_CASES"]),
                closed_case,
            )

    def test_case_number_from_case_dir_reads_directory_name(self) -> None:
        self.assertEqual(case_number_from_case_dir(Path("/tmp/B123456_Test_Case")), "B123456")

    def test_find_socf_odt_uses_case_number_socf_client_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "B123456_Test_Case"
            socf_dir = case_dir / "SOCF"
            socf_dir.mkdir(parents=True)
            expected = socf_dir / "B123456_SOCF_TR.odt"
            expected.write_text("", encoding="utf-8")
            (socf_dir / "SOCF.odt").write_text("", encoding="utf-8")
            (socf_dir / "B123456SOCFTR.odt").write_text("", encoding="utf-8")
            (socf_dir / "B123456_SOCF.pdf").write_text("", encoding="utf-8")

            self.assertEqual(find_socf_odt(case_dir), expected)

    def test_find_socf_odt_reports_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "B123456_Test_Case"
            (case_dir / "SOCF").mkdir(parents=True)

            with self.assertRaisesRegex(CurrentCaseError, "SOCF ODT not found"):
                find_socf_odt(case_dir)

    def test_current_case_socf_odt_reads_selected_case_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_name = "B123456_Test_Case"
            current_case_file = root / "currently_selected_case"
            current_case_file.write_text(f"{case_name}\n", encoding="utf-8")
            socf_dir = root / "OPEN_CASES" / case_name / "SOCF"
            socf_dir.mkdir(parents=True)
            expected = socf_dir / "B123456_SOCF_JM.odt"
            expected.write_text("", encoding="utf-8")

            self.assertEqual(
                current_case_socf_odt(
                    case_file=current_case_file,
                    roots=[root / "OPEN_CASES", root / "CLOSED_CASES"],
                ),
                expected,
            )

            resolved = current_case_socf(
                case_file=current_case_file,
                roots=[root / "OPEN_CASES", root / "CLOSED_CASES"],
            )
            self.assertEqual(resolved.case_name, case_name)
            self.assertEqual(resolved.case_dir, root / "OPEN_CASES" / case_name)
            self.assertEqual(resolved.path, expected)


if __name__ == "__main__":
    unittest.main()
