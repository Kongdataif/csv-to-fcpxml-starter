from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import make_xml
import preview_report as preview


class FakeMediaTools:
    def __init__(
        self,
        dimensions: dict[str, tuple[int, int]],
        *,
        ffmpeg_failure: str | None = None,
    ) -> None:
        self.dimensions = dimensions
        self.ffmpeg_failure = ffmpeg_failure
        self.commands: list[list[str]] = []

    def __call__(
        self, command: list[str], *, timeout_seconds: float
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        executable = Path(command[0]).name
        if "ffprobe" in executable:
            width, height = self.dimensions[Path(command[-1]).name]
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"streams": [{"width": width, "height": height}]}),
                stderr="",
            )
        if "ffmpeg" in executable:
            if self.ffmpeg_failure is not None:
                return subprocess.CompletedProcess(
                    command, 1, stdout="", stderr=self.ffmpeg_failure
                )
            Path(command[-1]).write_bytes(b"\xff\xd8preview\xff\xd9")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")


class PreviewReportTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        media = root / "Media"
        media.mkdir()
        (media / "wide & view.mp4").write_bytes(b"video")
        (media / "tall.jpg").write_bytes(b"image")
        return media

    @staticmethod
    def write_timeline(path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "id",
                    "kind",
                    "file",
                    "timeline_in",
                    "timeline_out",
                    "source_in",
                    "source_out",
                    "conform",
                    "portrait_conform",
                    "landscape_conform",
                    "notes",
                ]
            )
            writer.writerow(
                [
                    'A<&"',
                    "video",
                    "Media/wide & view.mp4",
                    "0",
                    "4",
                    "2",
                    "6",
                    "fit",
                    "fit",
                    "fill",
                    '<img src=x onerror="bad">',
                ]
            )
            writer.writerow(
                ["B", "image", "tall.jpg", "4", "7", "", "", "fill", "fill", "fill", ""]
            )

    @staticmethod
    def write_subtitles(path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["번호", "시작", "끝", "최종 대사", "장면 의도"])
            writer.writerow(
                [
                    "S<&",
                    "0.1",
                    "3.9",
                    '<script>alert("x")</script>\\n둘째 & 문장',
                    "악성처럼 보이는 입력",
                ]
            )
            writer.writerow(["S2", "4.2", "6.8", "두 번째 자막", "사진"])

    def test_generates_side_by_side_safe_html_and_jpegs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text).resolve()
            media = self.make_project(root)
            timeline = root / "timeline.csv"
            subtitles = root / "subtitles.csv"
            self.write_timeline(timeline)
            self.write_subtitles(subtitles)
            fake = FakeMediaTools(
                {"wide & view.mp4": (1920, 1080), "tall.jpg": (1080, 1920)}
            )

            with mock.patch.object(preview, "_run_process", side_effect=fake):
                report = preview.generate_preview_report(
                    timeline_csv=timeline,
                    subtitles_csv=subtitles,
                    project_root=root,
                    media_root=media,
                )

            self.assertEqual(report.index_path, root / "output" / "preview" / "index.html")
            self.assertTrue(report.index_path.is_file())
            self.assertEqual(len(list(report.assets_dir.glob("*.jpg"))), 2)
            self.assertEqual(len(report.scenes), 2)
            self.assertEqual(len(report.scenes[0].subtitles), 1)
            # Precision XML generation reads its effective common conform.
            # Direction columns are applied by make_xml's beginner adapter,
            # which supplies separate precision CSVs (covered below).
            self.assertEqual(report.scenes[0].scene.conform_for("portrait"), "fit")
            self.assertEqual(report.scenes[0].scene.conform_for("landscape"), "fit")

            ffmpeg_commands = [
                command for command in fake.commands if "ffmpeg" in Path(command[0]).name
            ]
            video_command = next(
                command for command in ffmpeg_commands if Path(command[command.index("-i") + 1]).suffix == ".mp4"
            )
            image_command = next(
                command for command in ffmpeg_commands if Path(command[command.index("-i") + 1]).suffix == ".jpg"
            )
            self.assertEqual(video_command[video_command.index("-ss") + 1], "4")
            self.assertNotIn("-ss", image_command)
            protocol_index = video_command.index("-protocol_whitelist")
            self.assertEqual(video_command[protocol_index + 1], "file")
            self.assertEqual(video_command[video_command.index("-f") + 1], "mov")
            self.assertIn("-enable_drefs", video_command)
            self.assertEqual(image_command[image_command.index("-f") + 1], "image2")
            self.assertEqual(
                image_command[image_command.index("-pattern_type") + 1], "none"
            )

            page = report.index_path.read_text(encoding="utf-8")
            self.assertIn("viewport portrait", page)
            self.assertIn("viewport landscape", page)
            self.assertIn("object-fit: contain;", page)
            self.assertIn("object-fit: cover;", page)
            self.assertIn("safe-area", page)
            self.assertIn("숏폼 공통 안전영역", page)
            self.assertIn("가로 보수적 안전영역", page)
            self.assertIn("top: 15%; right: 18%; bottom: 35%; left: 6%;", page)
            self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;<br>", page)
            self.assertIn("둘째 &amp; 문장", page)
            self.assertNotIn('<script>alert("x")</script>', page)
            self.assertIn("&lt;img src=x onerror=&quot;bad&quot;&gt;", page)
            self.assertIn("상·하 여백", page)
            self.assertIn("상·하가 합계", page)

    def test_layout_specific_csvs_are_paired_by_id_and_keep_each_conform(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text).resolve()
            media = self.make_project(root)
            portrait = root / "portrait.csv"
            landscape = root / "landscape.csv"
            header = "id,kind,file,timeline_in,timeline_out,source_in,source_out,conform\n"
            portrait.write_text(
                header + "A,video,Media/wide & view.mp4,0,4,2,6,fit\n",
                encoding="utf-8",
            )
            landscape.write_text(
                header + "A,video,Media/wide & view.mp4,0,4,2,6,fill\n",
                encoding="utf-8",
            )
            fake = FakeMediaTools({"wide & view.mp4": (1920, 1080)})

            with mock.patch.object(preview, "_run_process", side_effect=fake):
                report = preview.generate_preview_report(
                    timeline_csv_by_layout={
                        "portrait": portrait,
                        "landscape": landscape,
                    },
                    project_root=root,
                    media_root=media,
                    output_root=root / "Generated",
                )

            scene = report.scenes[0].scene
            self.assertEqual(scene.conform_for("portrait"), "fit")
            self.assertEqual(scene.conform_for("landscape"), "fill")
            self.assertEqual(report.index_path, root / "Generated" / "preview" / "index.html")
            page = report.index_path.read_text(encoding="utf-8")
            self.assertIn("세로 9:16</strong> · fit / object-fit: contain", page)
            self.assertIn("가로 16:9</strong> · fill / object-fit: cover", page)

    def test_layout_specific_csvs_reject_mismatched_scene_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = self.make_project(root)
            portrait = root / "portrait.csv"
            landscape = root / "landscape.csv"
            header = "id,kind,file,timeline_in,timeline_out,source_in,source_out,conform\n"
            portrait.write_text(
                header + "A,video,Media/wide & view.mp4,0,4,2,6,fit\n",
                encoding="utf-8",
            )
            landscape.write_text(
                header + "A,video,Media/wide & view.mp4,0,5,2,7,fill\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(preview.PreviewReportError, "timeline_out"):
                preview.generate_preview_report(
                    timeline_csv_by_layout={
                        "portrait": portrait,
                        "landscape": landscape,
                    },
                    project_root=root,
                    media_root=media,
                )

    def test_traversal_media_reference_is_rejected_before_tools_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            (root / "outside.mp4").write_bytes(b"secret")
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,../outside.mp4,0,1,0,1\n",
                encoding="utf-8",
            )

            with mock.patch.object(preview, "_run_process") as run:
                with self.assertRaisesRegex(preview.PreviewReportError, "상위 폴더 이동"):
                    preview.generate_preview_report(
                        timeline_csv=timeline,
                        project_root=root,
                        media_root=media,
                    )
            run.assert_not_called()

    def test_explicit_kind_cannot_enable_a_nested_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            (media / "playlist.m3u8").write_text(
                "#EXTM3U\n#EXTINF:1,\n../../outside.ts\n",
                encoding="utf-8",
            )
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,playlist.m3u8,0,1,0,1\n",
                encoding="utf-8",
            )

            with mock.patch.object(preview, "_run_process") as run:
                with self.assertRaisesRegex(
                    preview.PreviewReportError, "지원하지 않는 확장자"
                ):
                    preview.generate_preview_report(
                        timeline_csv=timeline,
                        project_root=root,
                        media_root=media,
                    )
            run.assert_not_called()

    def test_scene_limit_stops_uploaded_csv_before_external_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            (media / "clip.mp4").write_bytes(b"video")
            timeline = root / "timeline.csv"
            rows = [
                "id,kind,file,timeline_in,timeline_out,source_in,source_out",
                *(
                    f"C{index},video,clip.mp4,{index},{index + 1},0,1"
                    for index in range(preview.MAX_PREVIEW_SCENES + 1)
                ),
            ]
            timeline.write_text("\n".join(rows) + "\n", encoding="utf-8")

            with mock.patch.object(preview, "_run_process") as run:
                with self.assertRaisesRegex(preview.PreviewReportError, "최대 300개"):
                    preview.generate_preview_report(
                        timeline_csv=timeline,
                        project_root=root,
                        media_root=media,
                    )
            run.assert_not_called()

    def test_csv_and_subtitle_limits_stop_oversized_uploaded_plans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            (media / "clip.mp4").write_bytes(b"video")
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,clip.mp4,0,1,0,1\n",
                encoding="utf-8",
            )
            with mock.patch.object(preview, "MAX_PREVIEW_CSV_BYTES", 16):
                with self.assertRaisesRegex(preview.PreviewReportError, "파일이 미리보기 제한"):
                    preview.generate_preview_report(
                        timeline_csv=timeline,
                        project_root=root,
                        media_root=media,
                    )

            subtitles = root / "subtitles.csv"
            subtitle_rows = [
                "id,start,end,text",
                *(
                    f"S{index},{index},{index + 1},caption"
                    for index in range(preview.MAX_PREVIEW_SUBTITLES + 1)
                ),
            ]
            subtitles.write_text("\n".join(subtitle_rows) + "\n", encoding="utf-8")
            with mock.patch.object(preview, "_run_process") as run:
                with self.assertRaisesRegex(preview.PreviewReportError, "최대 5000개"):
                    preview.generate_preview_report(
                        timeline_csv=timeline,
                        subtitles_csv=subtitles,
                        project_root=root,
                        media_root=media,
                    )
            run.assert_not_called()

    def test_thumbnail_byte_limit_becomes_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = self.make_project(root)
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,Media/wide & view.mp4,0,1,0,1\n",
                encoding="utf-8",
            )
            fake = FakeMediaTools({"wide & view.mp4": (1920, 1080)})
            with mock.patch.object(preview, "_run_process", side_effect=fake), mock.patch.object(
                preview, "MAX_THUMBNAIL_BYTES", 4
            ):
                report = preview.generate_preview_report(
                    timeline_csv=timeline,
                    project_root=root,
                    media_root=media,
                )
            self.assertIsNone(report.scenes[0].thumbnail_path)
            self.assertTrue(any("크기 제한" in warning for warning in report.warnings))

    def test_total_timeout_skips_tools_and_writes_explicit_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = self.make_project(root)
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,Media/wide & view.mp4,0,1,0,1\n",
                encoding="utf-8",
            )

            with mock.patch.object(preview, "_run_process") as run, mock.patch.object(
                preview.time, "monotonic", side_effect=[0.0, 2.0, 2.0]
            ):
                report = preview.generate_preview_report(
                    timeline_csv=timeline,
                    project_root=root,
                    media_root=media,
                    total_timeout_seconds=1,
                )

            run.assert_not_called()
            self.assertIsNone(report.scenes[0].thumbnail_path)
            self.assertTrue(any("전체 미리보기 시간 제한" in item for item in report.warnings))
            self.assertIn(
                "전체 미리보기 시간 제한",
                report.index_path.read_text(encoding="utf-8"),
            )

    def test_terminal_controls_are_removed_from_warnings_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = self.make_project(root)
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out,conform\n"
                "A\x1b]0;forged-title\x07,video,Media/wide & view.mp4,0,1,0,1,fit\n",
                encoding="utf-8",
            )
            fake = FakeMediaTools({"wide & view.mp4": (1920, 1080)})

            with mock.patch.object(preview, "_run_process", side_effect=fake):
                report = preview.generate_preview_report(
                    timeline_csv=timeline,
                    project_root=root,
                    media_root=media,
                )
            self.assertTrue(report.warnings)
            self.assertTrue(all("\x1b" not in warning and "\x07" not in warning for warning in report.warnings))

            with mock.patch.object(
                preview, "_atomic_write_text", side_effect=PermissionError("denied\x1b[2J")
            ):
                with self.assertRaises(preview.PreviewReportError) as raised:
                    preview.generate_preview_report(
                        timeline_csv=timeline,
                        project_root=root,
                        media_root=media,
                        ffprobe_path="missing-ffprobe",
                        ffmpeg_path="missing-ffmpeg",
                    )
            self.assertNotIn("\x1b", str(raised.exception))

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_media_symlink_cannot_escape_media_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            outside = root / "outside.mp4"
            outside.write_bytes(b"secret")
            (media / "link.mp4").symlink_to(outside)
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,link.mp4,0,1,0,1\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(preview.PreviewReportError, "Media 폴더 밖"):
                preview.generate_preview_report(
                    timeline_csv=timeline,
                    project_root=root,
                    media_root=media,
                )

    def test_ffmpeg_failure_becomes_escaped_placeholder_and_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = self.make_project(root)
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out,conform\n"
                "A,video,Media/wide & view.mp4,0,4,2,6,fit\n",
                encoding="utf-8",
            )
            fake = FakeMediaTools(
                {"wide & view.mp4": (1920, 1080)},
                ffmpeg_failure='<decoder failed> & "unsafe"',
            )

            with mock.patch.object(preview, "_run_process", side_effect=fake):
                report = preview.generate_preview_report(
                    timeline_csv=timeline,
                    project_root=root,
                    media_root=media,
                )

            self.assertIsNone(report.scenes[0].thumbnail_path)
            self.assertFalse(list(report.assets_dir.glob("*.jpg")))
            self.assertTrue(any("썸네일 생성 실패" in item for item in report.warnings))
            page = report.index_path.read_text(encoding="utf-8")
            self.assertIn("placeholder", page)
            self.assertIn("썸네일 생성 실패", page)
            self.assertIn("&lt;decoder failed&gt; &amp; &quot;unsafe&quot;", page)
            self.assertNotIn("<decoder failed>", page)

    def test_missing_media_gets_placeholder_without_invoking_external_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,missing.mp4,0,1,0,1\n",
                encoding="utf-8",
            )

            with mock.patch.object(preview, "_run_process") as run:
                report = preview.generate_preview_report(
                    timeline_csv=timeline,
                    project_root=root,
                    media_root=media,
                )
            run.assert_not_called()
            self.assertIn("미디어 파일이 없습니다", report.index_path.read_text(encoding="utf-8"))

    def test_aspect_calculation_reports_axis_and_approximate_percent(self) -> None:
        portrait_fit = preview.calculate_layout_assessment(
            1920, 1080, layout="portrait", conform="fit"
        )
        portrait_fill = preview.calculate_layout_assessment(
            1920, 1080, layout="portrait", conform="fill"
        )
        self.assertEqual((portrait_fit.effect, portrait_fit.axis), ("letterbox", "vertical"))
        self.assertEqual((portrait_fill.effect, portrait_fill.axis), ("crop-x", "horizontal"))
        self.assertAlmostEqual(portrait_fit.total_percent or 0, 68.36, places=2)
        self.assertAlmostEqual(portrait_fill.total_percent or 0, 68.36, places=2)

    def test_output_root_outside_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text, tempfile.TemporaryDirectory() as outside_text:
            root = Path(temp_text)
            media = self.make_project(root)
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,Media/wide & view.mp4,0,1,0,1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(preview.PreviewReportError, "프로젝트 폴더 밖"):
                preview.generate_preview_report(
                    timeline_csv=timeline,
                    project_root=root,
                    media_root=media,
                    output_root=Path(outside_text),
                )


class PreviewOnlyIntegrationTests(unittest.TestCase):
    def test_beginner_both_preview_uses_directional_csvs_and_skips_xml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            (media / "still.png").write_bytes(b"placeholder")
            (root / "timeline.csv").write_text(
                "파일,사진 표시 시간(초),세로 화면 맞춤,가로 화면 맞춤\n"
                "still.png,1,화면 채우기,전체 보이기\n",
                encoding="utf-8",
            )
            captured_paths: list[Path] = []

            def fake_preview(**kwargs: object) -> SimpleNamespace:
                mapping = kwargs["timeline_csv_by_layout"]
                self.assertIsInstance(mapping, dict)
                assert isinstance(mapping, dict)
                self.assertEqual(set(mapping), {"portrait", "landscape"})
                conforms: dict[str, str] = {}
                for layout, raw_path in mapping.items():
                    path = Path(raw_path)
                    captured_paths.append(path)
                    self.assertTrue(path.is_file())
                    with path.open("r", encoding="utf-8-sig", newline="") as handle:
                        conforms[str(layout)] = next(csv.DictReader(handle))["conform"]
                self.assertEqual(conforms, {"portrait": "fill", "landscape": "fit"})
                self.assertEqual(kwargs["project_root"], root.resolve())
                self.assertEqual(kwargs["media_root"], media.resolve())
                self.assertEqual(kwargs["output_root"], root.resolve() / "Generated")
                self.assertEqual(kwargs["target_layouts"], ("portrait", "landscape"))
                return SimpleNamespace(
                    index_path=root / "Generated" / "preview" / "index.html",
                    warnings=(),
                )

            with mock.patch.object(make_xml.builder, "main", return_value=0) as build, mock.patch.object(
                make_xml.preview_report,
                "generate_preview_report",
                side_effect=fake_preview,
            ) as generate:
                result = make_xml.main(
                    [
                        str(root),
                        "--layout",
                        "both",
                        "--preview-only",
                        "--no-subtitles",
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(build.call_count, 2)
            for call in build.call_args_list:
                command = call.args[0]
                self.assertIn("--validate-only", command)
            self.assertTrue(captured_paths)
            self.assertTrue(all(not path.exists() for path in captured_paths))
            self.assertFalse(list(root.glob(".fcpxml_input_*")))


if __name__ == "__main__":
    unittest.main()
