from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest import mock

import csv_to_fcpxml as app


class TimeParsingTests(unittest.TestCase):
    def test_supported_time_formats(self) -> None:
        self.assertEqual(app.parse_time("01:02:03.500"), Fraction(7447, 2))
        self.assertEqual(app.parse_time("02:03,250"), Fraction(493, 4))
        self.assertEqual(app.parse_time("1.25"), Fraction(5, 4))

    def test_negative_time_is_rejected(self) -> None:
        with self.assertRaises(app.BuildError):
            app.parse_time("-0.001")

    def test_non_finite_time_is_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaises(app.BuildError):
                app.parse_time(value)

    def test_ntsc_aliases_are_exact(self) -> None:
        self.assertEqual(app.parse_fps("29.97"), Fraction(30000, 1001))
        self.assertEqual(app.parse_fps("59.94"), Fraction(60000, 1001))


class AtomicWriteTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_preexisting_fixed_tmp_symlink_cannot_redirect_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            target = root / "Generated" / "result.fcpxml"
            target.parent.mkdir()
            victim = root / "outside.txt"
            victim.write_text("keep", encoding="utf-8")
            target.with_name(target.name + ".tmp").symlink_to(victim)

            app.atomic_write_text(target, "safe output")

            self.assertEqual(target.read_text(encoding="utf-8"), "safe output")
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep")


class MediaTimeoutTests(unittest.TestCase):
    def test_ffprobe_pins_mov_demuxer_and_disables_external_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            media = Path(temp_text) / "clip.mov"
            media.touch()
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"format": {}, "streams": []}', stderr=""
            )
            with mock.patch.object(app, "require_command", return_value="ffprobe"), mock.patch.object(
                app.subprocess, "run", return_value=completed
            ) as run:
                app.probe_media(media)
            command = run.call_args.args[0]
            index = command.index("-protocol_whitelist")
            self.assertEqual(command[index + 1], "file")
            self.assertEqual(command[command.index("-f") + 1], "mov")
            self.assertEqual(command[command.index("-enable_drefs") + 1], "0")
            self.assertEqual(command[command.index("-use_absolute_path") + 1], "0")

    def test_ffprobe_timeout_becomes_a_friendly_build_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            media = Path(temp_text) / "damaged.mov"
            media.touch()
            expired = subprocess.TimeoutExpired(
                cmd=["ffprobe", str(media)], timeout=app.FFPROBE_TIMEOUT_SECONDS
            )
            with mock.patch.object(app, "require_command", return_value="ffprobe"), mock.patch.object(
                app.subprocess, "run", side_effect=expired
            ):
                with self.assertRaisesRegex(app.BuildError, "60초.*손상"):
                    app.probe_media(media)


class TimelineTests(unittest.TestCase):
    def test_non_frame_time_is_snapped_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            (root / "clip.mp4").touch()
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,clip.mp4,0.001,1.001,0,1\n",
                encoding="utf-8",
            )
            clips, warnings = app.load_timeline(
                timeline,
                project_root=root,
                fps=Fraction(30),
                frame_tolerance=Fraction(1, 60),
            )
            self.assertEqual(clips[0].timeline_in, 0)
            self.assertEqual(clips[0].timeline_out, 1)
            self.assertEqual(len(warnings), 1)

    def test_extra_csv_value_has_friendly_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            (root / "clip.mp4").touch()
            timeline = root / "timeline.csv"
            timeline.write_text(
                "id,kind,file,timeline_in,timeline_out\n"
                "A,video,clip.mp4,0,1,unexpected\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(app.BuildError, "헤더보다 값이 많습니다"):
                app.load_timeline(
                    timeline,
                    project_root=root,
                    fps=Fraction(30),
                    frame_tolerance=Fraction(1, 60),
                )


class ImageCacheTests(unittest.TestCase):
    def test_cache_filename_stays_within_portable_byte_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            image = root / (("긴사진" * 19) + ".png")
            image.write_bytes(b"demo")
            cache = app.image_cache_path(
                image_path=image,
                output_root=root / "Generated",
                clip_id="I" * 300,
                duration=Fraction(3),
                width=1080,
                height=1920,
                fps=Fraction(30),
                conform="fit",
                background="#000000",
            )
            self.assertLessEqual(len(cache.name.encode("utf-8")), 240)
            self.assertTrue(cache.name.endswith(".mp4"))

    def test_cache_key_changes_with_render_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            image = root / "photo.png"
            image.write_bytes(b"demo")
            common = {
                "image_path": image,
                "output_root": root / "Generated",
                "clip_id": "I01",
                "width": 1080,
                "height": 1920,
                "fps": Fraction(30),
                "conform": "fit",
                "background": "#000000",
            }
            first = app.image_cache_path(duration=Fraction(2), **common)
            second = app.image_cache_path(duration=Fraction(3), **common)
            third = app.image_cache_path(duration=Fraction(2), **{**common, "background": "#ffffff"})
            self.assertNotEqual(first, second)
            self.assertNotEqual(first, third)

    def test_cache_hit_removes_legacy_temporary_file_without_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            image = root / "photo.png"
            output = root / "Generated" / "cached.mp4"
            output.parent.mkdir()
            image.write_bytes(b"image")
            output.write_bytes(b"cached")
            output.touch()
            legacy_temporary = output.with_name("cached.tmp.mp4")
            legacy_temporary.write_bytes(b"orphan")

            with mock.patch.object(app, "require_command") as require_command:
                rendered = app.render_image_as_video(
                    image_path=image,
                    output_path=output,
                    duration=Fraction(1),
                    width=1080,
                    height=1920,
                    fps=Fraction(30),
                    conform="fit",
                    background="#000000",
                )

            self.assertFalse(rendered)
            self.assertFalse(legacy_temporary.exists())
            require_command.assert_not_called()


class CaptionTests(unittest.TestCase):
    def test_caption_time_is_snapped_to_project_frames(self) -> None:
        captions = [app.CaptionRow("C1", Fraction(1, 1000), Fraction(1001, 1000), "hello", "")]
        normalized, warnings = app.snap_captions_to_frames(captions, fps=Fraction(30))
        self.assertEqual(normalized[0].start, 0)
        self.assertEqual(normalized[0].end, 1)
        self.assertEqual(len(warnings), 1)


class XmlGenerationTests(unittest.TestCase):
    def make_media_info(self, duration: int = 20, *, audio: bool = True) -> app.MediaInfo:
        return app.MediaInfo(
            duration=Fraction(duration),
            width=1920,
            height=1080,
            fps=Fraction(30),
            has_video=True,
            has_audio=audio,
            audio_rate=48000 if audio else None,
            audio_channels=2 if audio else None,
        )

    def test_nested_caption_offset_uses_parent_local_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "clip.mp4"
            media.touch()
            clip = app.ClipRow(
                row_number=2,
                clip_id="A",
                kind="video",
                file_text="clip.mp4",
                file_path=media,
                timeline_in=Fraction(5),
                timeline_out=Fraction(7),
                source_in=Fraction(10),
                source_out=Fraction(12),
                conform="fit",
                include_audio=False,
                volume_db=Decimal(0),
                notes="trimmed source",
                media_info=self.make_media_info(),
            )
            caption = app.CaptionRow("C1", Fraction(11, 2), Fraction(13, 2), "hello", "")
            output = root / "Generated" / "test.fcpxml"
            config = {
                "fps": "30",
                "width": 1920,
                "height": 1080,
                "path_mode": "relative",
                "captions": {"format": "ITT", "placement": "bottom"},
            }
            app.build_fcpxml(
                output_path=output,
                config=config,
                clips=[clip],
                captions=[caption],
                embed_captions=True,
                bgm=None,
            )
            root_element = ET.parse(output).getroot()
            caption_element = root_element.find(".//caption")
            self.assertIsNotNone(caption_element)
            self.assertEqual(caption_element.get("offset"), "21/2s")

    def test_bgm_before_first_clip_attaches_to_leading_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            video = root / "clip.mp4"
            audio = root / "bed.m4a"
            video.touch()
            audio.touch()
            clip = app.ClipRow(
                row_number=2,
                clip_id="A",
                kind="video",
                file_text="clip.mp4",
                file_path=video,
                timeline_in=Fraction(2),
                timeline_out=Fraction(4),
                source_in=Fraction(0),
                source_out=Fraction(2),
                conform="fit",
                include_audio=False,
                volume_db=Decimal(0),
                notes="",
                media_info=self.make_media_info(),
            )
            bgm_info = app.MediaInfo(Fraction(4), None, None, None, False, True, 48000, 2)
            bgm = app.AudioBed(audio, bgm_info, Fraction(0), Fraction(0), Fraction(4), Decimal(-12), "music")
            output = root / "Generated" / "test.fcpxml"
            config = {"fps": "30", "width": 1920, "height": 1080, "path_mode": "relative"}
            app.build_fcpxml(
                output_path=output,
                config=config,
                clips=[clip],
                captions=[],
                embed_captions=False,
                bgm=bgm,
            )
            root_element = ET.parse(output).getroot()
            connected_audio = root_element.find(".//spine/gap/asset-clip")
            self.assertIsNotNone(connected_audio)
            self.assertEqual(connected_audio.get("offset"), "0s")

    def test_relative_media_uri_encodes_korean_space_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            media = root / "Media" / "카페 첫 #부팅.mov"
            media.parent.mkdir()
            media.touch()
            output = root / "Generated" / "result.fcpxml"
            uri = app.media_src(media, output_path=output, path_mode="relative")
            self.assertTrue(uri.startswith("../Media/"))
            self.assertNotIn(" ", uri)
            self.assertNotIn("#", uri)
            self.assertIn("%23", uri)


class CliTests(unittest.TestCase):
    def test_validate_only_does_not_create_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            (root / "clip.mp4").touch()
            (root / "timeline.csv").write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,clip.mp4,0,1,0,1\n",
                encoding="utf-8",
            )
            (root / "project.json").write_text(
                json.dumps(
                    {
                        "width": 1920,
                        "height": 1080,
                        "fps": "30",
                        "timeline_csv": "timeline.csv",
                        "output_dir": "Generated",
                        "image_mode": "direct",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(app, "prepare_clips"), mock.patch.object(app, "prepare_bgm", return_value=None):
                result = app.main(["--config", str(root / "project.json"), "--validate-only"])
            self.assertEqual(result, 0)
            self.assertFalse((root / "Generated").exists())

    def test_restrict_to_project_root_blocks_normalized_header_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            workspace = Path(temp_text)
            root = workspace / "project"
            root.mkdir()
            outside = workspace / "outside.mp4"
            outside.touch()
            (root / "timeline.csv").write_text(
                "id,kind, FILE ,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,../outside.mp4,0,1,0,1\n",
                encoding="utf-8",
            )
            (root / "project.json").write_text(
                json.dumps(
                    {
                        "width": 1920,
                        "height": 1080,
                        "fps": "30",
                        "timeline_csv": "timeline.csv",
                        "output_dir": "Generated",
                        "image_mode": "direct",
                    }
                ),
                encoding="utf-8",
            )
            result = app.main(
                ["--config", str(root / "project.json"), "--validate-only", "--restrict-to-project-root"]
            )
            self.assertEqual(result, 2)

    def test_external_output_requires_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            workspace = Path(temp_text)
            root = workspace / "project"
            root.mkdir()
            (root / "clip.mp4").touch()
            (root / "timeline.csv").write_text(
                "id,kind,file,timeline_in,timeline_out,source_in,source_out\n"
                "A,video,clip.mp4,0,1,0,1\n",
                encoding="utf-8",
            )
            config = root / "project.json"
            config.write_text(
                json.dumps(
                    {
                        "width": 1920,
                        "height": 1080,
                        "fps": "30",
                        "timeline_csv": "timeline.csv",
                        "output_dir": "../outside-generated",
                        "image_mode": "direct",
                    }
                ),
                encoding="utf-8",
            )

            blocked = app.main(["--config", str(config), "--validate-only"])
            self.assertEqual(blocked, 2)

            with mock.patch.object(app, "prepare_clips"), mock.patch.object(
                app, "prepare_bgm", return_value=None
            ):
                allowed = app.main(
                    [
                        "--config",
                        str(config),
                        "--validate-only",
                        "--allow-external-output",
                    ]
                )
            self.assertEqual(allowed, 0)
            self.assertFalse((workspace / "outside-generated").exists())


if __name__ == "__main__":
    unittest.main()
