from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest import mock

import csv_to_fcpxml as app
import make_xml
from scripts.validate_fcpxml import validate


def media_info(duration: int = 10) -> app.MediaInfo:
    return app.MediaInfo(
        duration=Fraction(duration),
        width=1080,
        height=1920,
        fps=Fraction(30),
        has_video=True,
        has_audio=True,
        audio_rate=48000,
        audio_channels=2,
    )


def clip(root: Path, clip_id: str, start: int, end: int) -> app.ClipRow:
    path = root / f"{clip_id}.mp4"
    path.touch()
    return app.ClipRow(
        row_number=2,
        clip_id=clip_id,
        kind="video",
        file_text=path.name,
        file_path=path,
        timeline_in=Fraction(start),
        timeline_out=Fraction(end),
        source_in=Fraction(0),
        source_out=Fraction(end - start),
        conform="fit",
        include_audio=True,
        volume_db=Decimal(0),
        notes="",
        media_info=media_info(),
    )


class SubtitleOptionTests(unittest.TestCase):
    def test_new_file_defaults_to_title_and_srt(self) -> None:
        options = app.normalize_subtitle_options({"subtitles": {"file": "subtitles.csv"}})
        self.assertEqual(options.mode, "title")
        self.assertTrue(options.generate_srt)
        self.assertFalse(options.legacy)

    def test_legacy_caption_semantics_are_preserved(self) -> None:
        embedded = app.normalize_subtitle_options(
            {"captions": {"file": "captions.csv", "embed": True}}
        )
        srt_only = app.normalize_subtitle_options(
            {"captions": {"file": "captions.csv", "embed": False}}
        )
        self.assertEqual(embedded.mode, "caption")
        self.assertEqual(srt_only.mode, "off")
        self.assertTrue(embedded.generate_srt)
        self.assertTrue(srt_only.generate_srt)

    def test_new_and_legacy_settings_cannot_be_mixed(self) -> None:
        with self.assertRaisesRegex(app.BuildError, "동시에 설정"):
            app.validate_config(
                {
                    "subtitles": {"file": "subtitles.csv"},
                    "captions": {"file": "captions.csv"},
                }
            )


class TitleXmlTests(unittest.TestCase):
    def test_basic_title_structure_style_position_and_cross_cut_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            output = root / "Generated" / "with_titles.fcpxml"
            captions = [
                app.CaptionRow(
                    "S1",
                    Fraction(3, 2),
                    Fraction(5, 2),
                    "system neo: 안녕 & <테스트>",
                    "",
                )
            ]
            config = {
                "fps": "30",
                "width": 1080,
                "height": 1920,
                "path_mode": "relative",
                "subtitles": {
                    "file": "subtitles.csv",
                    "mode": "title",
                    "role": "System Neo",
                    "font": "NeoDunggeunmo Code",
                    "font_size": 44,
                    "position_y": -720,
                    "outline_width": -3,
                    "shadow": True,
                    "prefix": "system neo:",
                },
            }
            app.build_fcpxml(
                output_path=output,
                config=config,
                clips=[clip(root, "A", 0, 2), clip(root, "B", 2, 4)],
                captions=captions,
                embed_captions=False,
                embed_titles=True,
                bgm=None,
            )
            tree = ET.parse(output)
            root_element = tree.getroot()
            effect = root_element.find("./resources/effect")
            title = root_element.find(".//title")
            self.assertIsNotNone(effect)
            self.assertEqual(effect.get("id"), "rBasicTitle")
            self.assertTrue(effect.get("uid"))
            self.assertIsNotNone(title)
            self.assertEqual(title.get("ref"), "rBasicTitle")
            self.assertEqual(title.get("role"), "titles.System Neo")
            self.assertEqual(title.get("duration"), "1s")
            self.assertIsNone(root_element.find(".//caption"))
            transform = title.find("adjust-transform")
            self.assertEqual(transform.get("position"), "0 -37.5")
            style = title.find("text-style-def/text-style")
            self.assertEqual(style.get("font"), "NeoDunggeunmo Code")
            self.assertEqual(style.get("fontSize"), "44")
            self.assertEqual(style.get("strokeWidth"), "-3")
            self.assertEqual(style.get("shadowOffset"), "2 -2")
            rendered_text = "".join(title.find("text").itertext())
            self.assertEqual(rendered_text, "system neo:\n안녕 & <테스트>")
            self.assertEqual(validate(output, check_media=False), [])


class SubtitleOutputMatrixTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        (root / "Media").mkdir()
        (root / "Media" / "clip.mp4").touch()
        (root / "timeline.csv").write_text(
            "파일,시작,끝\nclip.mp4,0,4\n",
            encoding="utf-8",
        )
        (root / "subtitles.csv").write_text(
            "번호,시작,끝,대사,메모\nS1,0.2,1.8,첫 번째 자막,테스트\n",
            encoding="utf-8",
        )
        return root / "project.json"

    @staticmethod
    def fake_prepare(clips: list[app.ClipRow], **_: object) -> None:
        for item in clips:
            item.media_info = media_info()

    def write_config(self, path: Path, mode: str, srt: bool = True) -> None:
        path.write_text(
            json.dumps(
                {
                    "output_basename": "matrix",
                    "width": 1080,
                    "height": 1920,
                    "fps": "30",
                    "timeline_csv": "timeline.csv",
                    "media_dir": "Media",
                    "output_dir": "Generated",
                    "path_mode": "relative",
                    "image_mode": "direct",
                    "subtitles": {
                        "file": "subtitles.csv",
                        "mode": mode,
                        "srt": srt,
                    },
                    "captions": {},
                }
            ),
            encoding="utf-8",
        )

    def run_builder(self, config: Path) -> int:
        with mock.patch.object(app, "prepare_clips", side_effect=self.fake_prepare), mock.patch.object(
            app, "prepare_bgm", return_value=None
        ):
            return app.main(["--config", str(config), "--restrict-to-project-root"])

    def test_both_then_title_removes_stale_caption_and_respects_srt_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            config = self.make_project(root)
            self.write_config(config, "both", srt=True)
            self.assertEqual(self.run_builder(config), 0)
            generated = root / "Generated"
            self.assertTrue((generated / "matrix_clean.fcpxml").is_file())
            self.assertTrue((generated / "matrix_with_titles.fcpxml").is_file())
            self.assertTrue((generated / "matrix_with_captions.fcpxml").is_file())
            self.assertTrue((generated / "matrix.srt").is_file())

            self.write_config(config, "title", srt=False)
            self.assertEqual(self.run_builder(config), 0)
            self.assertTrue((generated / "matrix_with_titles.fcpxml").is_file())
            self.assertFalse((generated / "matrix_with_captions.fcpxml").exists())
            self.assertFalse((generated / "matrix.srt").exists())

    def test_off_with_srt_creates_only_clean_and_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            config = self.make_project(root)
            self.write_config(config, "off", srt=True)
            self.assertEqual(self.run_builder(config), 0)
            names = {path.name for path in (root / "Generated").iterdir() if path.is_file()}
            self.assertEqual(names, {"matrix_clean.fcpxml", "matrix.srt", "build_report.txt"})

    def test_new_subtitle_config_does_not_add_system_neo_prefix_to_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            config = self.make_project(root)
            self.write_config(config, "title", srt=True)
            self.assertEqual(self.run_builder(config), 0)

            srt = (root / "Generated" / "matrix.srt").read_text(encoding="utf-8")
            self.assertIn("\n첫 번째 자막\n", srt)
            self.assertNotIn("system neo:", srt.lower())

    def test_no_srt_preserves_legacy_caption_style_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            config = self.make_project(root)
            config.write_text(
                json.dumps(
                    {
                        "output_basename": "legacy",
                        "width": 1080,
                        "height": 1920,
                        "fps": "30",
                        "timeline_csv": "timeline.csv",
                        "media_dir": "Media",
                        "output_dir": "Generated",
                        "path_mode": "relative",
                        "image_mode": "direct",
                        "captions": {"file": "subtitles.csv", "embed": True},
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                app, "prepare_clips", side_effect=self.fake_prepare
            ), mock.patch.object(app, "prepare_bgm", return_value=None):
                result = app.main(
                    [
                        "--config",
                        str(config),
                        "--restrict-to-project-root",
                        "--no-srt",
                    ]
                )

            self.assertEqual(result, 0)
            generated = root / "Generated"
            self.assertFalse((generated / "legacy.srt").exists())
            xml_root = ET.parse(generated / "legacy_with_captions.fcpxml").getroot()
            caption = xml_root.find(".//caption")
            self.assertIsNotNone(caption)
            assert caption is not None
            self.assertEqual(caption.get("role"), "System Neo?captionFormat=ITT.ko-KR")
            styles = xml_root.findall(".//caption/text-style-def/text-style")
            self.assertTrue(styles)
            self.assertTrue(all(style.get("bold") == "1" for style in styles))


class QuickSubtitleDiscoveryTests(unittest.TestCase):
    def test_auto_detects_root_subtitles_and_unique_dialogue_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            direct = root / "subtitles.csv"
            direct.touch()
            self.assertEqual(make_xml.choose_subtitles(root, None, disabled=False), direct.resolve())
            direct.unlink()
            docs = root / "Docs"
            docs.mkdir()
            dialogue = docs / "system_neo_대사표.csv"
            dialogue.touch()
            self.assertEqual(make_xml.choose_subtitles(root, None, disabled=False), dialogue.resolve())

    def test_open_prefers_title_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text).resolve()
            (root / "Media").mkdir()
            (root / "Media" / "clip.mp4").touch()
            (root / "timeline.csv").write_text(
                "파일,시작,끝\nclip.mp4,0,1\n",
                encoding="utf-8",
            )
            (root / "subtitles.csv").touch()
            output_name = app.safe_output_basename(root.name)
            generated = root / "Generated"
            generated.mkdir()
            (generated / f"{output_name}_clean.fcpxml").touch()
            (generated / f"{output_name}_with_titles.fcpxml").touch()
            with mock.patch.object(make_xml.builder, "main", return_value=0), mock.patch(
                "open_in_final_cut.open_fcpxml", return_value=0
            ) as opener:
                result = make_xml.main([str(root), "--open"])
            self.assertEqual(result, 0)
            self.assertEqual(
                opener.call_args.args[0],
                root / "Generated" / f"{output_name}_with_titles.fcpxml",
            )

    def test_open_falls_back_to_clean_when_subtitle_csv_has_no_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text).resolve()
            (root / "Media").mkdir()
            (root / "Media" / "clip.mp4").touch()
            (root / "timeline.csv").write_text(
                "파일,시작,끝\nclip.mp4,0,1\n",
                encoding="utf-8",
            )
            (root / "subtitles.csv").write_text(
                "번호,시작,끝,대사,메모\n",
                encoding="utf-8",
            )
            output_name = app.safe_output_basename(root.name)

            def fake_build(_: list[str]) -> int:
                generated = root / "Generated"
                generated.mkdir()
                (generated / f"{output_name}_clean.fcpxml").touch()
                return 0

            with mock.patch.object(make_xml.builder, "main", side_effect=fake_build), mock.patch(
                "open_in_final_cut.open_fcpxml", return_value=0
            ) as opener:
                result = make_xml.main([str(root), "--open"])

            self.assertEqual(result, 0)
            self.assertEqual(
                opener.call_args.args[0],
                root / "Generated" / f"{output_name}_clean.fcpxml",
            )


if __name__ == "__main__":
    unittest.main()
