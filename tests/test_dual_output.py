from __future__ import annotations

import csv
import tempfile
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from unittest import mock

import csv_to_fcpxml as builder
import make_xml
import open_in_final_cut
from scripts.validate_fcpxml import validate


def fake_media_info(*, width: int = 1920, height: int = 1080) -> builder.MediaInfo:
    return builder.MediaInfo(
        duration=Fraction(2),
        width=width,
        height=height,
        fps=Fraction(30),
        has_video=True,
        has_audio=True,
        audio_rate=48000,
        audio_channels=2,
        video_duration=Fraction(2),
    )


class DualOutputBuilderTests(unittest.TestCase):
    @staticmethod
    def make_precision_project(root: Path) -> None:
        media = root / "Media"
        media.mkdir()
        (media / "clip.mp4").touch()
        (root / "timeline.csv").write_text(
            "id,kind,file,timeline_in,timeline_out,source_in,source_out,"
            "conform,include_audio,volume_db,notes,enabled\n"
            "C01,video,clip.mp4,0,2,0,2,fit,false,0,test,true\n",
            encoding="utf-8",
        )
        (root / "subtitles.csv").write_text(
            "번호,시작,끝,대사\nS01,0.2,1.8,세로와 가로 자막 위치 확인\n",
            encoding="utf-8",
        )

    def test_new_both_layout_shares_input_and_separates_every_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = (Path(temp_text) / "dual_demo").resolve()
            root.mkdir()
            self.make_precision_project(root)
            prepare_targets: list[tuple[Path, int, int]] = []

            def fake_prepare(clips: list[builder.ClipRow], **kwargs: object) -> None:
                output_root = kwargs["output_root"]
                width = int(kwargs["project_width"])
                height = int(kwargs["project_height"])
                assert isinstance(output_root, Path)
                prepare_targets.append((output_root, width, height))
                for clip in clips:
                    clip.media_info = fake_media_info()

            original_load = builder.load_timeline
            with mock.patch.object(
                builder, "load_timeline", wraps=original_load
            ) as load_timeline, mock.patch.object(
                builder, "prepare_clips", side_effect=fake_prepare
            ), mock.patch.object(builder, "prepare_bgm", return_value=None):
                result = builder.main(
                    [
                        "--quick-project",
                        str(root),
                        "--timeline",
                        str(root / "timeline.csv"),
                        "--subtitles",
                        str(root / "subtitles.csv"),
                        "--subtitle-mode",
                        "title",
                        "--layout",
                        "both",
                        "--path-mode",
                        "relative",
                    ]
                )

            self.assertEqual(result, 0)
            load_timeline.assert_called_once()
            self.assertEqual(
                prepare_targets,
                [
                    (root / "Generated" / "vertical_9x16", 1080, 1920),
                    (root / "Generated" / "horizontal_16x9", 1920, 1080),
                ],
            )

            expectations = {
                "portrait": ("vertical_9x16", 1080, 1920, "-12.5", "[세로 9:16]"),
                "landscape": (
                    "horizontal_16x9",
                    1920,
                    1080,
                    "-37.5",
                    "[가로 16:9]",
                ),
            }
            for layout, (folder, width, height, y_percent, project_suffix) in expectations.items():
                output_root = root / "Generated" / folder
                basename = f"dual_demo_{folder}"
                clean = output_root / f"{basename}_clean.fcpxml"
                titled = output_root / f"{basename}_with_titles.fcpxml"
                report = output_root / "build_report.txt"
                self.assertTrue(clean.is_file())
                self.assertTrue(titled.is_file())
                self.assertTrue((output_root / f"{basename}.srt").is_file())
                self.assertTrue(report.is_file())

                self.assertEqual(
                    validate(
                        titled,
                        check_media=False,
                        expected_width=width,
                        expected_height=height,
                        expected_fps="30",
                    ),
                    [],
                )
                xml_root = ET.parse(titled).getroot()
                project = xml_root.find("./event/project")
                self.assertIsNotNone(project)
                assert project is not None
                self.assertTrue(project.get("name", "").endswith(project_suffix))
                transform = xml_root.find(".//title/adjust-transform")
                self.assertIsNotNone(transform)
                assert transform is not None
                self.assertEqual(transform.get("position"), f"0 {y_percent}")
                report_text = report.read_text(encoding="utf-8")
                self.assertIn(f"Frame size: {width}x{height}", report_text)
                self.assertIn("Frame rate: 30 fps", report_text)

                wrong_width = 1920 if width == 1080 else 1080
                errors = validate(
                    titled,
                    check_media=False,
                    expected_width=wrong_width,
                    expected_height=height,
                    expected_fps="30",
                )
                self.assertTrue(any("width가 예상과 다릅니다" in error for error in errors))

    def test_legacy_landscape_alias_keeps_the_original_output_location(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text) / "legacy_demo"
            root.mkdir()
            self.make_precision_project(root)

            def fake_prepare(clips: list[builder.ClipRow], **_: object) -> None:
                for clip in clips:
                    clip.media_info = fake_media_info()

            with mock.patch.object(
                builder, "prepare_clips", side_effect=fake_prepare
            ), mock.patch.object(builder, "prepare_bgm", return_value=None):
                result = builder.main(
                    ["--quick-project", str(root), "--landscape", "--no-subtitles"]
                )

            self.assertEqual(result, 0)
            output = root / "Generated" / "legacy_demo_clean.fcpxml"
            self.assertTrue(output.is_file())
            self.assertFalse((root / "Generated" / "horizontal_16x9").exists())
            self.assertEqual(
                validate(
                    output,
                    check_media=False,
                    expected_width=1920,
                    expected_height=1080,
                    expected_fps=30,
                ),
                [],
            )

    def test_variant_suffix_survives_a_long_korean_project_name(self) -> None:
        long_name = "긴프로젝트" * 50
        for layout, suffix in (
            ("portrait", "vertical_9x16"),
            ("landscape", "horizontal_16x9"),
        ):
            config = builder.quick_config(
                Path("/tmp/example"),
                project_name=long_name,
                landscape=layout == "landscape",
                fps="30",
                media_dir="Media",
                layout=layout,
            )
            variant = builder.layout_variant_config(
                config,
                layout=layout,
                distinct_output=True,
            )
            basename = str(variant["output_basename"])
            self.assertTrue(basename.endswith(f"_{suffix}"))
            self.assertLessEqual(len(basename.encode("utf-8")), 180)


class DualOutputBeginnerAdapterTests(unittest.TestCase):
    def test_both_uses_each_direction_specific_conform_column(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media"
            media.mkdir()
            (media / "still.png").touch()
            (root / "timeline.csv").write_text(
                "파일,사진 표시 시간(초),화면 자막,화면 맞춤,"
                "세로 화면 맞춤,가로 화면 맞춤\n"
                "still.png,1,테스트 자막,전체 보이기,화면 채우기,전체 보이기\n",
                encoding="utf-8",
            )
            observed: list[tuple[str, str, bool]] = []

            def inspect_command(command: list[str]) -> int:
                layout = command[command.index("--layout") + 1]
                timeline_path = Path(command[command.index("--timeline") + 1])
                with timeline_path.open("r", encoding="utf-8", newline="") as handle:
                    conform = next(csv.DictReader(handle))["conform"]
                observed.append((layout, conform, "--validate-only" in command))
                return 0

            with mock.patch.object(builder, "main", side_effect=inspect_command):
                result = make_xml.main([str(root), "--layout", "both"])

            self.assertEqual(result, 0)
            self.assertEqual(
                observed,
                [
                    ("portrait", "fill", True),
                    ("landscape", "fit", True),
                    ("portrait", "fill", False),
                    ("landscape", "fit", False),
                ],
            )
            self.assertFalse(any(root.glob(".fcpxml_input_*")))

    def test_both_open_sends_each_layout_title_xml_to_final_cut(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = (Path(temp_text) / "open_both").resolve()
            media = root / "Media"
            media.mkdir(parents=True)
            (media / "clip.mp4").touch()
            (root / "timeline.csv").write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out,"
                "conform,include_audio,volume_db,notes,enabled\n"
                "C01,video,clip.mp4,0,1,0,1,fit,false,0,test,true\n",
                encoding="utf-8",
            )
            (root / "subtitles.csv").write_text(
                "번호,시작,끝,대사\nS01,0,1,열기 테스트\n",
                encoding="utf-8",
            )

            def fake_builder(command: list[str]) -> int:
                if "--validate-only" in command:
                    return 0
                layout = command[command.index("--layout") + 1]
                profile = builder.LAYOUT_PROFILES[layout]
                output_root = root / "Generated" / str(profile["folder"])
                output_root.mkdir(parents=True, exist_ok=True)
                output_name = builder.suffixed_output_basename(
                    root.name,
                    str(profile["basename_suffix"]),
                )
                (output_root / f"{output_name}_with_titles.fcpxml").write_text(
                    '<fcpxml version="1.14"/>',
                    encoding="utf-8",
                )
                return 0

            with mock.patch.object(
                builder, "main", side_effect=fake_builder
            ), mock.patch.object(
                open_in_final_cut, "open_fcpxml", return_value=0
            ) as open_xml:
                result = make_xml.main([str(root), "--layout", "both", "--open"])

            self.assertEqual(result, 0)
            expected = []
            for layout in ("portrait", "landscape"):
                profile = builder.LAYOUT_PROFILES[layout]
                output_name = builder.suffixed_output_basename(
                    root.name,
                    str(profile["basename_suffix"]),
                )
                expected.append(
                    mock.call(
                        root
                        / "Generated"
                        / str(profile["folder"])
                        / f"{output_name}_with_titles.fcpxml"
                    )
                )
            self.assertEqual(open_xml.call_args_list, expected)


if __name__ == "__main__":
    unittest.main()
