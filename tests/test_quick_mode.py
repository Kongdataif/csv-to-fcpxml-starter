from __future__ import annotations

import csv
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction
from pathlib import Path
from unittest import mock

import csv_to_fcpxml as builder
import make_xml
import open_in_final_cut


class QuickTimelineTests(unittest.TestCase):
    def test_output_basename_is_portable_for_long_korean_project_name(self) -> None:
        basename = builder.safe_output_basename("긴프로젝트" * 40)
        self.assertLessEqual(len(basename.encode("utf-8")), 180)
        self.assertTrue(basename)

    def make_project(self, root: Path, file_value: str = "clip.mp4") -> tuple[Path, Path]:
        media = root / "Media"
        media.mkdir()
        (media / "clip.mp4").touch()
        timeline = root / "timeline.csv"
        timeline.write_text(
            "파일,시작,끝\n"
            f"{file_value},00:00:00.000,00:00:02.000\n",
            encoding="utf-8",
        )
        return media, timeline

    def test_bare_filename_resolves_inside_media_and_keeps_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media, timeline = self.make_project(root)
            clips, _ = builder.load_timeline(
                timeline,
                project_root=root,
                media_root=media,
                fps=Fraction(30),
                frame_tolerance=Fraction(1, 60),
                restrict_to_project_root=True,
                require_media_root=True,
                default_include_audio=True,
            )
            self.assertEqual(clips[0].file_path, (media / "clip.mp4").resolve())
            self.assertTrue(clips[0].include_audio)

    def test_media_prefix_is_also_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media, timeline = self.make_project(root, "Media/clip.mp4")
            clips, _ = builder.load_timeline(
                timeline,
                project_root=root,
                media_root=media,
                fps=Fraction(30),
                frame_tolerance=Fraction(1, 60),
                restrict_to_project_root=True,
                require_media_root=True,
            )
            self.assertEqual(clips[0].file_path, (media / "clip.mp4").resolve())

    def test_existing_file_outside_media_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            (root / "clip.mp4").touch()
            timeline = root / "timeline.csv"
            timeline.write_text("파일,시작,끝\nclip.mp4,0,1\n", encoding="utf-8")
            with self.assertRaisesRegex(builder.BuildError, "Media 폴더 안"):
                builder.load_timeline(
                    timeline,
                    project_root=root,
                    media_root=media,
                    fps=Fraction(30),
                    frame_tolerance=Fraction(1, 60),
                    restrict_to_project_root=True,
                    require_media_root=True,
                )


class QuickCliTests(unittest.TestCase):
    def test_validate_only_needs_no_project_json_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text) / "나의 첫 영상"
            root.mkdir()
            self.make_project_files(root)
            with mock.patch.object(builder, "prepare_clips"), mock.patch.object(
                builder, "prepare_bgm", return_value=None
            ):
                result = make_xml.main([str(root), "--validate-only"])
            self.assertEqual(result, 0)
            self.assertFalse((root / "project.json").exists())
            self.assertFalse((root / "Generated").exists())

    @staticmethod
    def make_project_files(root: Path) -> None:
        (root / "Media").mkdir()
        (root / "Media" / "clip.mp4").touch()
        (root / "timeline.csv").write_text(
            "파일,시작,끝\nclip.mp4,0,1\n",
            encoding="utf-8",
        )

    @staticmethod
    def make_beginner_project(
        root: Path,
        *,
        title: str = "첫 화면 자막",
        filename: str = "still.png",
    ) -> tuple[Path, Path]:
        """사진 한 장짜리 간편 CSV 프로젝트를 만든다.

        사진은 영상 길이 검사용 ffprobe가 필요하지 않으므로, 이 헬퍼를 쓰는
        테스트는 간편 CSV 어댑터와 CLI 전달 규칙에만 집중할 수 있다.
        """

        media = root / "Media"
        media.mkdir()
        (media / filename).touch()
        timeline = root / "timeline.csv"
        timeline.write_text(
            "파일,사진 표시 시간(초),화면 자막,소리,화면 맞춤,메모\n"
            f"{filename},2.5,{title},,전체 보이기,오프닝\n",
            encoding="utf-8",
        )
        return media, timeline

    def test_beginner_inline_title_is_adapted_and_forwarded_to_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text) / "첫 프로젝트"
            root.mkdir()
            media, _ = self.make_beginner_project(root, title="안녕하세요 System Neo")
            captured: dict[str, object] = {}

            def inspect_builder(command: list[str]) -> int:
                # make_xml의 임시 폴더가 살아 있는 동안 기존 엔진에 전달될
                # 정밀 타임라인과 자막 CSV의 실제 내용을 검사한다.
                captured["command"] = tuple(command)
                timeline_path = Path(command[command.index("--timeline") + 1])
                subtitle_path = Path(command[command.index("--subtitles") + 1])
                self.assertTrue(timeline_path.is_file())
                self.assertTrue(subtitle_path.is_file())
                with timeline_path.open("r", encoding="utf-8", newline="") as handle:
                    captured["timeline_rows"] = list(csv.DictReader(handle))
                with subtitle_path.open("r", encoding="utf-8", newline="") as handle:
                    captured["subtitle_rows"] = list(csv.DictReader(handle))
                captured["temporary_root"] = timeline_path.parent
                return 0

            stdout = io.StringIO()
            with mock.patch.object(builder, "main", side_effect=inspect_builder), redirect_stdout(stdout):
                result = make_xml.main([str(root)])

            self.assertEqual(result, 0)
            command = captured["command"]
            assert isinstance(command, tuple)
            self.assertEqual(command[command.index("--subtitle-mode") + 1], "title")
            self.assertEqual(command[command.index("--path-mode") + 1], "relative")
            self.assertEqual(Path(command[command.index("--media-dir") + 1]), media.resolve())

            timeline_rows = captured["timeline_rows"]
            subtitle_rows = captured["subtitle_rows"]
            assert isinstance(timeline_rows, list)
            assert isinstance(subtitle_rows, list)
            self.assertEqual(timeline_rows[0]["kind"], "image")
            self.assertEqual(timeline_rows[0]["timeline_out"], "2.5")
            self.assertEqual(timeline_rows[0]["include_audio"], "false")
            self.assertEqual(subtitle_rows[0]["최종 대사"], "안녕하세요 System Neo")
            self.assertEqual((subtitle_rows[0]["시작"], subtitle_rows[0]["끝"]), ("0", "2.5"))
            self.assertIn("간편 CSV 확인: 장면 1개", stdout.getvalue())
            self.assertFalse(Path(captured["temporary_root"]).exists())

    def test_beginner_inline_title_conflicts_with_external_subtitles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            self.make_beginner_project(root)
            (root / "subtitles.csv").write_text(
                "번호,시작,끝,최종 대사\nS001,0,1,별도 자막\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with mock.patch.object(builder, "main") as builder_main, redirect_stderr(stderr):
                result = make_xml.main([str(root)])

            self.assertEqual(result, 2)
            builder_main.assert_not_called()
            self.assertIn("자막 입력이 두 곳", stderr.getvalue())
            self.assertFalse(any(root.glob(".fcpxml_input_*")))

    def test_no_subtitles_suppresses_beginner_inline_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            self.make_beginner_project(root)
            captured: list[str] = []

            def inspect_builder(command: list[str]) -> int:
                captured.extend(command)
                return 0

            with mock.patch.object(builder, "main", side_effect=inspect_builder):
                result = make_xml.main([str(root), "--no-subtitles"])

            self.assertEqual(result, 0)
            self.assertIn("--no-subtitles", captured)
            self.assertNotIn("--subtitles", captured)
            self.assertNotIn("--subtitle-mode", captured)
            self.assertFalse(any(root.glob(".fcpxml_input_*")))

    def test_beginner_validate_only_writes_no_output_and_removes_adapter_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            self.make_beginner_project(root, title="")

            # 실제 builder.main의 validate-only 분기를 통과시킨다. 사진 파일은
            # 빈 테스트 파일이므로 미디어 probe/렌더 단계만 가짜로 대체한다.
            with mock.patch.object(builder, "prepare_clips") as prepare, mock.patch.object(
                builder, "prepare_bgm", return_value=None
            ):
                result = make_xml.main([str(root), "--validate-only"])

            self.assertEqual(result, 0)
            prepare.assert_called_once()
            self.assertFalse((root / "Generated").exists())
            self.assertFalse(any(root.glob(".fcpxml_input_*")))

    def test_outside_media_directory_is_rejected_before_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            base = Path(temp_text)
            root = base / "project"
            outside_media = base / "outside-media"
            root.mkdir()
            outside_media.mkdir()
            (outside_media / "clip.mp4").touch()
            (root / "timeline.csv").write_text("파일\nclip.mp4\n", encoding="utf-8")
            stderr = io.StringIO()

            with mock.patch.object(builder, "probe_media") as probe, mock.patch.object(
                builder, "main"
            ) as builder_main, redirect_stderr(stderr):
                result = make_xml.main(
                    [str(root), "--media-dir", str(outside_media.resolve())]
                )

            self.assertEqual(result, 2)
            probe.assert_not_called()
            builder_main.assert_not_called()
            self.assertIn("Media 폴더 경로가 프로젝트 폴더 밖", stderr.getvalue())

    def test_quick_config_has_explicit_portrait_and_landscape_defaults(self) -> None:
        root = Path("/tmp/example")
        portrait = builder.quick_config(
            root, project_name=None, landscape=False, fps="30", media_dir="Media"
        )
        landscape = builder.quick_config(
            root, project_name="Wide", landscape=True, fps="30000/1001", media_dir="Media"
        )
        self.assertEqual((portrait["width"], portrait["height"]), (1080, 1920))
        self.assertEqual((landscape["width"], landscape["height"]), (1920, 1080))
        self.assertEqual(landscape["fps"], "30000/1001")


class OpenInFinalCutTests(unittest.TestCase):
    def test_mac_helper_passes_valid_xml_to_final_cut(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            path = (Path(temp_text) / "result.fcpxml").resolve()
            path.write_text('<?xml version="1.0"?><fcpxml version="1.14"/>', encoding="utf-8")
            completed = subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(open_in_final_cut.sys, "platform", "darwin"), mock.patch.object(
                open_in_final_cut.subprocess, "run", side_effect=[completed, completed]
            ) as run:
                result = open_in_final_cut.open_fcpxml(path)
            self.assertEqual(result, 0)
            self.assertEqual(run.call_args_list[1].args[0], ["open", "-a", "Final Cut Pro", str(path)])

    def test_helper_rejects_non_mac(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            path = Path(temp_text) / "result.fcpxml"
            path.write_text('<fcpxml version="1.14"/>', encoding="utf-8")
            with mock.patch.object(open_in_final_cut.sys, "platform", "linux"):
                self.assertEqual(open_in_final_cut.open_fcpxml(path), 2)


if __name__ == "__main__":
    unittest.main()
