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
    find_current_case_documents,
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

    def test_find_current_case_documents_returns_every_markdown_copy_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "B123456_Test_Case"
            first_reply = case_dir / "A" / "suggested_reply_arguments.md"
            second_reply = case_dir / "B" / "suggested_reply_arguments.md"
            respondent = (
                case_dir
                / "Respondent"
                / "suggested_respondents_brief_arguments.md"
            )
            opposition = case_dir / "Opposition" / "suggested_opposition_arguments.md"
            for path in (first_reply, second_reply, respondent, opposition):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Report\n", encoding="utf-8")
            (case_dir / "A" / "suggested_reply_arguments.html").write_text(
                "<html></html>",
                encoding="utf-8",
            )
            (case_dir / "A" / "suggested_reply_arguments.txt").write_text(
                "spoken text",
                encoding="utf-8",
            )
            (case_dir / "A" / "notes.md").write_text("notes", encoding="utf-8")

            documents = find_current_case_documents(case_dir)

            self.assertEqual(
                [(document.kind, document.relative_path.as_posix()) for document in documents],
                [
                    ("reply", "A/suggested_reply_arguments.md"),
                    ("reply", "B/suggested_reply_arguments.md"),
                    (
                        "respondent",
                        "Respondent/suggested_respondents_brief_arguments.md",
                    ),
                    ("opposition", "Opposition/suggested_opposition_arguments.md"),
                ],
            )

    def test_find_current_case_documents_ignores_outside_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "B123456_Test_Case"
            link_dir = case_dir / "Linked"
            link_dir.mkdir(parents=True)
            outside = root / "suggested_reply_arguments.md"
            outside.write_text("# Outside\n", encoding="utf-8")
            (link_dir / "suggested_reply_arguments.md").symlink_to(outside)

            self.assertEqual(find_current_case_documents(case_dir), ())

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
