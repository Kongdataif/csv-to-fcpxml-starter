from __future__ import annotations

import csv
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import simple_timeline
import spreadsheet_input
from scripts.validate_fcpxml import validate


REPO_ROOT = Path(__file__).resolve().parents[1]
QUICK_START = REPO_ROOT / "examples" / "quick_start" / "timeline.csv"
PREVIEW_ROOT = REPO_ROOT / "examples" / "preview_output"


class PublishedExampleTests(unittest.TestCase):
    def test_relative_markdown_links_point_to_existing_files(self) -> None:
        missing: list[str] = []
        markdown_files = list(REPO_ROOT.glob("*.md"))
        markdown_files.extend((REPO_ROOT / "docs").glob("*.md"))
        markdown_files.extend((REPO_ROOT / "examples").rglob("*.md"))

        for markdown in markdown_files:
            text = markdown.read_text(encoding="utf-8")
            for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", text):
                target = match.group(1).strip().split(maxsplit=1)[0].strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if relative and not (markdown.parent / relative).resolve().exists():
                    missing.append(f"{markdown.relative_to(REPO_ROOT)} -> {target}")

        self.assertEqual(missing, [])

    def test_start_here_has_the_three_roles_in_order(self) -> None:
        text = (REPO_ROOT / "START_HERE.md").read_text(encoding="utf-8")
        stages = (
            "## 0. 개발자가 Mac에서 먼저 확인",
            "## 1. GitHub에 공개",
            "## 2. 초보 사용자가 실행",
        )
        positions = [text.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Mac 로컬 — 기본 권장", text)
        self.assertIn("GitHub ID는 이 단계의 **업로드 담당자**에게만 필요", text)
        self.assertIn("timeline.xlsx 또는 timeline.csv", text)

    def test_quick_start_uses_the_six_beginner_columns(self) -> None:
        with QUICK_START.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        self.assertEqual(
            reader.fieldnames,
            [
                "파일",
                "영상 원본 시작",
                "영상 원본 끝",
                "사진 표시 시간(초)",
                "화면 자막",
                "소리",
            ],
        )
        self.assertEqual(simple_timeline.detect_csv_mode(QUICK_START), "beginner")
        self.assertEqual(len(rows), 3)
        self.assertTrue(any(row["사진 표시 시간(초)"] for row in rows))
        self.assertTrue(
            any(row["영상 원본 시작"] and row["영상 원본 끝"] for row in rows)
        )
        self.assertTrue(
            any(not row["영상 원본 시작"] and not row["영상 원본 끝"] for row in rows)
        )
        for row in rows:
            filename = row["파일"]
            self.assertEqual(PurePosixPath(filename).name, filename)
            self.assertFalse(Path(filename).is_absolute())

    def test_published_csv_templates_are_excel_friendly_utf8_bom(self) -> None:
        csv_paths = sorted((REPO_ROOT / "templates").glob("*.csv"))
        csv_paths.extend(sorted((REPO_ROOT / "examples").rglob("*.csv")))
        self.assertEqual(len(csv_paths), 15)
        self.assertIn(
            REPO_ROOT / "examples" / "multi_format" / "timeline.csv",
            csv_paths,
        )
        for path in csv_paths:
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_excel_templates_match_the_published_csv_examples(self) -> None:
        pairs = (
            (
                REPO_ROOT / "templates" / "simple_timeline.csv",
                REPO_ROOT / "templates" / "simple_timeline.xlsx",
                "timeline",
                5_000,
            ),
            (
                REPO_ROOT / "templates" / "subtitles_template.csv",
                REPO_ROOT / "templates" / "subtitles_template.xlsx",
                "subtitles",
                10_000,
            ),
            (
                REPO_ROOT / "examples" / "multi_format" / "timeline.csv",
                REPO_ROOT / "templates" / "multi_format_timeline.xlsx",
                "timeline",
                5_000,
            ),
        )
        for csv_path, xlsx_path, kind, max_rows in pairs:
            with self.subTest(template=xlsx_path.name):
                self.assertTrue(xlsx_path.read_bytes().startswith(b"PK"))
                converted, canonical, description = spreadsheet_input.decode_uploaded_plan(
                    xlsx_path.name,
                    xlsx_path.read_bytes(),
                    kind=kind,
                    max_rows=max_rows,
                )
                expected_rows = list(
                    csv.reader(csv_path.read_text(encoding="utf-8-sig").splitlines())
                )
                actual_rows = list(csv.reader(converted.splitlines()))
                self.assertEqual(actual_rows, expected_rows)
                self.assertTrue(canonical.startswith(b"\xef\xbb\xbf"))
                self.assertIn("Excel 파일", description)

    def test_preview_fcpxml_is_structurally_valid_and_portable(self) -> None:
        clean = PREVIEW_ROOT / "quick_start_clean.fcpxml"
        titles = PREVIEW_ROOT / "quick_start_with_titles.fcpxml"
        for path in (clean, titles):
            self.assertEqual(
                validate(path, check_media=False, require_relative=True),
                [],
            )
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?:file://|/content/|/Users/|/tmp/)")
            root = ET.parse(path).getroot()
            sequence = root.find("./event/project/sequence")
            self.assertIsNotNone(sequence)
            assert sequence is not None
            self.assertEqual(sequence.get("duration"), "8s")

        self.assertEqual(len(ET.parse(clean).getroot().findall(".//title")), 0)
        self.assertEqual(len(ET.parse(titles).getroot().findall(".//title")), 3)
        self.assertEqual(len(ET.parse(titles).getroot().findall(".//caption")), 0)

    def test_preview_srt_matches_the_three_scenes(self) -> None:
        text = (PREVIEW_ROOT / "quick_start.srt").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"(?m)^\d+$", text)), 3)
        for timing in (
            "00:00:00,000 --> 00:00:02,000",
            "00:00:02,000 --> 00:00:05,000",
            "00:00:05,000 --> 00:00:08,000",
        ):
            self.assertIn(timing, text)
        for subtitle in (
            "첫 장면입니다",
            "사진을 3초 보여 줍니다",
            "마지막 3초 구간입니다",
        ):
            self.assertIn(subtitle, text)


if __name__ == "__main__":
    unittest.main()
