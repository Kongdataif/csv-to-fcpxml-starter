from __future__ import annotations

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from fractions import Fraction
from pathlib import Path
from unittest import mock

import csv_to_fcpxml as builder
import make_xml
import make_xml_input as subject


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPOSITORY_ROOT / "templates"


class MacInputDiscoveryTests(unittest.TestCase):
    def test_timeline_xlsx_and_csv_are_ambiguous_until_explicitly_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            xlsx = root / "timeline.xlsx"
            csv_path = root / "timeline.csv"
            xlsx.write_bytes((TEMPLATES / "simple_timeline.xlsx").read_bytes())
            csv_path.write_text("파일\nstill.png\n", encoding="utf-8")

            with self.assertRaisesRegex(builder.BuildError, "(?s)여러 개.*--timeline"):
                subject.choose_timeline(root, None)

            self.assertEqual(
                subject.choose_timeline(root, "timeline.xlsx"),
                xlsx.resolve(),
            )
            self.assertEqual(
                subject.choose_timeline(root, "timeline.csv"),
                csv_path.resolve(),
            )

    def test_unique_nonstandard_xlsx_name_keeps_existing_fallback_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            plan = root / "첫 영상 기획.xlsx"
            plan.write_bytes((TEMPLATES / "simple_timeline.xlsx").read_bytes())
            (root / "subtitles.xlsx").write_bytes(
                (TEMPLATES / "subtitles_template.xlsx").read_bytes()
            )

            self.assertEqual(subject.choose_timeline(root, None), plan.resolve())

    def test_subtitle_xlsx_and_dialogue_sheet_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            direct = root / "subtitles.xlsx"
            direct.write_bytes((TEMPLATES / "subtitles_template.xlsx").read_bytes())
            self.assertEqual(
                subject.choose_subtitles(root, None, disabled=False),
                direct.resolve(),
            )

            direct.unlink()
            docs = root / "Docs"
            docs.mkdir()
            dialogue = docs / "촬영본_대사표.xlsx"
            dialogue.write_bytes((TEMPLATES / "subtitles_template.xlsx").read_bytes())
            self.assertEqual(
                subject.choose_subtitles(root, None, disabled=False),
                dialogue.resolve(),
            )

    def test_multiple_subtitle_formats_require_explicit_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            csv_path = root / "subtitles.csv"
            csv_path.touch()
            docs = root / "Docs"
            docs.mkdir()
            xlsx_path = docs / "subtitles.xlsx"
            xlsx_path.touch()

            with self.assertRaisesRegex(builder.BuildError, "(?s)여러 개.*--subtitles"):
                subject.choose_subtitles(root, None, disabled=False)
            self.assertEqual(
                subject.choose_subtitles(
                    root,
                    "subtitles.csv",
                    disabled=False,
                ),
                csv_path.resolve(),
            )
            self.assertEqual(
                subject.choose_subtitles(
                    root,
                    "Docs/subtitles.xlsx",
                    disabled=False,
                ),
                xlsx_path.resolve(),
            )

    def test_numbers_inputs_show_excel_export_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            # A Numbers document may appear as a regular file or as a package
            # directory on macOS; explicit selection must reject either before
            # trying to read its internals.
            (root / "timeline.numbers").mkdir()
            (root / "subtitles.numbers").touch()

            with self.assertRaisesRegex(
                builder.BuildError,
                "파일 → 다음으로 내보내기 → Excel",
            ):
                subject.choose_timeline(root, None)
            with self.assertRaisesRegex(
                builder.BuildError,
                "파일 → 다음으로 내보내기 → Excel",
            ):
                subject.choose_subtitles(
                    root,
                    "subtitles.numbers",
                    disabled=False,
                )

    def test_requested_input_cannot_escape_the_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            workspace = Path(temp_text)
            root = workspace / "project"
            root.mkdir()
            outside = workspace / "timeline.csv"
            outside.touch()

            with self.assertRaisesRegex(builder.BuildError, "프로젝트 폴더 밖"):
                subject.choose_timeline(root, outside)


class MacInputPreparationTests(unittest.TestCase):
    def test_csv_is_passed_through_without_decode_or_temporary_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            timeline = root / "timeline.csv"
            timeline.write_bytes(b"\xef\xbb\xbf\xed\x8c\x8c\xec\x9d\xbc\nphoto.png\n")

            with mock.patch.object(
                subject,
                "decode_uploaded_plan",
                side_effect=AssertionError("CSV must not be decoded"),
            ):
                with subject.prepare_plan_csv(
                    timeline,
                    project_root=root,
                    kind="timeline",
                ) as prepared:
                    self.assertEqual(prepared.source_path, timeline.resolve())
                    self.assertEqual(prepared.csv_path, timeline.resolve())
                    self.assertFalse(prepared.converted)
                    self.assertEqual(prepared.source_description, "CSV 파일")
                    self.assertEqual(list(root.glob(".fcpxml_input_*")), [])

            self.assertTrue(timeline.is_file())

    def test_timeline_and_subtitles_xlsx_use_kind_limits_and_are_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            timeline = root / "timeline.xlsx"
            subtitles = root / "subtitles.xlsx"
            timeline_bytes = (TEMPLATES / "simple_timeline.xlsx").read_bytes()
            subtitle_bytes = (TEMPLATES / "subtitles_template.xlsx").read_bytes()
            timeline.write_bytes(timeline_bytes)
            subtitles.write_bytes(subtitle_bytes)
            generated = root / "Generated"
            generated.mkdir()
            marker = generated / "keep.txt"
            marker.write_text("사용자 결과", encoding="utf-8")

            temporary_csvs: list[Path] = []
            with mock.patch.object(
                subject,
                "decode_uploaded_plan",
                wraps=subject.decode_uploaded_plan,
            ) as decoder:
                with subject.prepare_mac_inputs(root) as prepared:
                    self.assertTrue(prepared.timeline.converted)
                    self.assertIsNotNone(prepared.subtitles)
                    assert prepared.subtitles is not None
                    self.assertTrue(prepared.subtitles.converted)
                    self.assertEqual(prepared.timeline.source_path, timeline.resolve())
                    self.assertEqual(prepared.subtitles.source_path, subtitles.resolve())

                    temporary_csvs = [
                        prepared.timeline.csv_path,
                        prepared.subtitles.csv_path,
                    ]
                    for path in temporary_csvs:
                        self.assertTrue(path.is_file())
                        self.assertIn(root.resolve(), path.resolve().parents)
                        self.assertNotIn(generated.resolve(), path.resolve().parents)
                        self.assertTrue(path.parent.name.startswith(".fcpxml_input_"))

                    with prepared.timeline.csv_path.open(
                        "r", encoding="utf-8-sig", newline=""
                    ) as handle:
                        timeline_rows = list(csv.reader(handle))
                    with prepared.subtitles.csv_path.open(
                        "r", encoding="utf-8-sig", newline=""
                    ) as handle:
                        subtitle_rows = list(csv.reader(handle))
                    self.assertEqual(timeline_rows[0][0], "파일")
                    self.assertEqual(subtitle_rows[0][:4], ["번호", "시작", "끝", "최종 대사"])

                calls = {
                    call.kwargs["kind"]: call.kwargs["max_rows"]
                    for call in decoder.call_args_list
                }

            self.assertEqual(
                calls,
                {
                    "timeline": subject.MAX_TIMELINE_ROWS,
                    "subtitles": subject.MAX_SUBTITLE_ROWS,
                },
            )
            self.assertTrue(all(not path.exists() for path in temporary_csvs))
            self.assertEqual(list(root.glob(".fcpxml_input_*")), [])
            self.assertEqual(timeline.read_bytes(), timeline_bytes)
            self.assertEqual(subtitles.read_bytes(), subtitle_bytes)
            self.assertEqual(marker.read_text(encoding="utf-8"), "사용자 결과")

    def test_invalid_xlsx_cleans_temporary_directory_and_preserves_generated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            (root / "timeline.xlsx").write_bytes(b"not an Excel workbook")
            generated = root / "Generated"
            generated.mkdir()
            marker = generated / "existing.fcpxml"
            marker.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(builder.BuildError, "올바른 .xlsx"):
                with subject.prepare_mac_inputs(root, no_subtitles=True):
                    self.fail("invalid Excel must fail before yielding")

            self.assertEqual(list(root.glob(".fcpxml_input_*")), [])
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_oversized_xlsx_is_bounded_before_decoder_and_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            (root / "timeline.xlsx").write_bytes(b"x" * 17)

            with mock.patch.object(subject, "MAX_XLSX_BYTES", 16), mock.patch.object(
                subject,
                "decode_uploaded_plan",
                side_effect=AssertionError("oversized input must not reach decoder"),
            ):
                with self.assertRaisesRegex(builder.BuildError, "10 MiB"):
                    with subject.prepare_mac_inputs(root, no_subtitles=True):
                        self.fail("oversized Excel must fail before yielding")

            self.assertEqual(list(root.glob(".fcpxml_input_*")), [])

    def test_no_subtitles_skips_an_existing_subtitle_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            timeline = root / "timeline.csv"
            timeline.write_text("파일\nphoto.png\n", encoding="utf-8")
            (root / "subtitles.xlsx").write_bytes(b"intentionally invalid")

            with subject.prepare_mac_inputs(root, no_subtitles=True) as prepared:
                self.assertEqual(prepared.timeline.csv_path, timeline.resolve())
                self.assertIsNone(prepared.subtitles)

            with self.assertRaisesRegex(
                builder.BuildError,
                "--no-subtitles.*--subtitles",
            ):
                with subject.prepare_mac_inputs(
                    root,
                    subtitles="subtitles.xlsx",
                    no_subtitles=True,
                ):
                    self.fail("conflicting subtitle options must fail before yielding")


class MacMainXlsxIntegrationTests(unittest.TestCase):
    @staticmethod
    def _video_info() -> builder.MediaInfo:
        return builder.MediaInfo(
            duration=Fraction(30),
            width=1920,
            height=1080,
            fps=Fraction(30),
            has_video=True,
            has_audio=True,
            audio_rate=48_000,
            audio_channels=2,
            video_duration=Fraction(30),
        )

    @staticmethod
    def _write_fake_report(root: Path, command: list[str]) -> None:
        timeline = Path(command[command.index("--timeline") + 1])
        subtitles = (
            Path(command[command.index("--subtitles") + 1])
            if "--subtitles" in command
            else None
        )

        def portable(path: Path) -> str:
            return path.resolve().relative_to(root.resolve()).as_posix()

        lines = [f"Timeline CSV: {portable(timeline)}"]
        if subtitles is not None:
            lines.append(f"Subtitle CSV: {portable(subtitles)}")
        lines.extend(("", "Clip map:", "- fake integration report"))
        generated = root / "Generated"
        generated.mkdir(exist_ok=True)
        (generated / "build_report.txt").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def test_main_builds_beginner_timeline_xlsx_and_reports_original_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            timeline = root / "timeline.xlsx"
            timeline.write_bytes((TEMPLATES / "simple_timeline.xlsx").read_bytes())
            media = root / "Media"
            media.mkdir()
            for name in ("cafe_boot.mov", "ipad_drawing.png", "office.mp4"):
                (media / name).touch()

            observed_paths: list[Path] = []

            def fake_builder(command: list[str]) -> int:
                effective_timeline = Path(command[command.index("--timeline") + 1])
                effective_subtitles = Path(command[command.index("--subtitles") + 1])
                observed_paths.extend((effective_timeline, effective_subtitles))
                self.assertTrue(effective_timeline.is_file())
                self.assertTrue(effective_subtitles.is_file())
                self.assertNotEqual(effective_timeline, timeline.resolve())
                self.assertTrue(any(root.glob(".fcpxml_input_*")))
                self._write_fake_report(root, command)
                return 0

            with mock.patch.object(
                builder,
                "probe_media",
                return_value=self._video_info(),
            ), mock.patch.object(builder, "main", side_effect=fake_builder):
                result = make_xml.main([str(root)])

            self.assertEqual(result, 0)
            self.assertTrue(all(not path.exists() for path in observed_paths))
            self.assertFalse(any(root.glob(".fcpxml_input_*")))
            self.assertTrue(timeline.is_file())
            report = (root / "Generated" / "build_report.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "Timeline input: timeline.xlsx (Excel 파일 · 시트: timeline)",
                report,
            )
            self.assertIn(
                "Subtitle input: timeline.xlsx의 '화면 자막' 열 "
                "(Excel 파일 · 시트: timeline)",
                report,
            )
            self.assertNotIn(".fcpxml_input_", report)
            self.assertIn("Input preparation:", report)

    def test_main_builds_external_subtitles_xlsx_and_rewrites_precision_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            (media / "still.png").touch()
            timeline = root / "timeline.csv"
            timeline.write_text(
                "파일,시작,끝\nstill.png,0,10\n",
                encoding="utf-8",
            )
            subtitles = root / "subtitles.xlsx"
            subtitles.write_bytes(
                (TEMPLATES / "subtitles_template.xlsx").read_bytes()
            )
            observed_subtitle: Path | None = None

            def fake_builder(command: list[str]) -> int:
                nonlocal observed_subtitle
                self.assertEqual(
                    Path(command[command.index("--timeline") + 1]),
                    timeline.resolve(),
                )
                observed_subtitle = Path(command[command.index("--subtitles") + 1])
                self.assertTrue(observed_subtitle.is_file())
                self.assertNotEqual(observed_subtitle, subtitles.resolve())
                with observed_subtitle.open(
                    "r", encoding="utf-8-sig", newline=""
                ) as handle:
                    rows = list(csv.reader(handle))
                self.assertEqual(rows[0][:4], ["번호", "시작", "끝", "최종 대사"])
                self._write_fake_report(root, command)
                return 0

            with mock.patch.object(builder, "main", side_effect=fake_builder):
                result = make_xml.main([str(root)])

            self.assertEqual(result, 0)
            self.assertIsNotNone(observed_subtitle)
            assert observed_subtitle is not None
            self.assertFalse(observed_subtitle.exists())
            self.assertFalse(any(root.glob(".fcpxml_input_*")))
            report = (root / "Generated" / "build_report.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("Timeline input: timeline.csv (CSV 파일)", report)
            self.assertIn(
                "Subtitle input: subtitles.xlsx (Excel 파일 · 시트: subtitles)",
                report,
            )
            self.assertNotIn(".fcpxml_input_", report)

    def test_cli_help_names_both_spreadsheet_formats(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as context, redirect_stdout(stdout):
            make_xml.main(["--help"])

        self.assertEqual(context.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("timeline.xlsx", help_text)
        self.assertIn("timeline.csv", help_text)
        self.assertIn("subtitles.xlsx/.csv", help_text)


class DocumentationInputContractTests(unittest.TestCase):
    def test_beginner_docs_match_timeline_subtitle_and_numbers_selection(self) -> None:
        documents = (
            REPOSITORY_ROOT / "README.md",
            REPOSITORY_ROOT / "docs" / "MAC.md",
            REPOSITORY_ROOT / "docs" / "USER_GUIDE.md",
        )

        for path in documents:
            with self.subTest(document=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("timeline.xlsx", text)
                self.assertIn("timeline.csv", text)
                self.assertIn("자동 우선순위가 없습니다", text)
                self.assertIn("--timeline", text)
                self.assertIn("subtitles.xlsx", text)
                self.assertIn("subtitles.csv", text)
                self.assertIn("--subtitles", text)
                self.assertIn("--no-subtitles", text)
                self.assertIn("Docs/", text)
                self.assertIn("대사표", text)
                self.assertIn("동시에", text)
                self.assertIn(".numbers", text)
                self.assertIn("파일 > 다음으로 내보내기 > Excel", text)


if __name__ == "__main__":
    unittest.main()
