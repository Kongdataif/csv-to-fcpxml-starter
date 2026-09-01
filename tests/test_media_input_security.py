from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

import csv_to_fcpxml as builder


class MediaInputPolicyTests(unittest.TestCase):
    def test_all_published_extensions_have_a_pinned_demuxer(self) -> None:
        expected = (
            builder.VIDEO_EXTENSIONS
            | builder.IMAGE_EXTENSIONS
            | builder.AUDIO_EXTENSIONS
        )
        self.assertEqual(set(builder.MEDIA_INPUT_POLICIES), expected)
        for suffix, policy in builder.MEDIA_INPUT_POLICIES.items():
            with self.subTest(suffix=suffix):
                self.assertTrue(policy.demuxer)
                self.assertNotIn(policy.demuxer, {"hls", "concat"})

    def test_playlist_extension_and_kind_switches_are_rejected_before_ffprobe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            playlist = root / "attack.m3u8"
            playlist.write_text("#EXTM3U\n../outside.mov\n", encoding="utf-8")
            disguised_video = root / "attack.mp4"
            disguised_video.write_text("#EXTM3U\n../outside.mov\n", encoding="utf-8")

            with mock.patch.object(builder, "require_command") as require_command:
                with self.assertRaisesRegex(builder.BuildError, "자동 형식 감지"):
                    builder.probe_media(playlist)
                with self.assertRaisesRegex(builder.BuildError, "확장자와 kind"):
                    builder.probe_media(disguised_video, expected_kind="image")
            require_command.assert_not_called()

    def test_disguised_hls_and_concat_are_forced_to_the_file_extension_demuxer(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"format": {}, "streams": []}),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            cases = {
                "playlist.mp4": "mov",
                "concat.avi": "avi",
                "playlist.mkv": "matroska,webm",
                "playlist.webm": "matroska,webm",
            }
            for name, demuxer in cases.items():
                path = root / name
                path.write_text("#EXTM3U\n../outside.mov\n", encoding="utf-8")
                with self.subTest(name=name), mock.patch.object(
                    builder, "require_command", return_value="ffprobe"
                ), mock.patch.object(
                    builder.subprocess, "run", return_value=completed
                ) as run:
                    builder.probe_media(path)
                    command = run.call_args.args[0]
                    self.assertEqual(command[command.index("-f") + 1], demuxer)
                    self.assertEqual(
                        command[command.index("-protocol_whitelist") + 1],
                        "file",
                    )

    def test_image_render_disables_patterns_and_forces_image2(self) -> None:
        rendered_info = builder.MediaInfo(
            duration=Fraction(1),
            width=1080,
            height=1920,
            fps=Fraction(30),
            has_video=True,
            has_audio=False,
            audio_rate=None,
            audio_channels=None,
            video_duration=Fraction(1),
        )
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            image = root / "frame%03d.png"
            image.write_bytes(b"not decoded by this command-boundary test")
            output = root / "Generated" / "cached.mp4"
            with mock.patch.object(
                builder, "require_command", return_value="ffmpeg"
            ), mock.patch.object(
                builder.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as run, mock.patch.object(
                builder, "probe_media", return_value=rendered_info
            ):
                self.assertTrue(
                    builder.render_image_as_video(
                        image_path=image,
                        output_path=output,
                        duration=Fraction(1),
                        width=1080,
                        height=1920,
                        fps=Fraction(30),
                        conform="fit",
                        background="#000000",
                    )
                )

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-f") + 1], "image2")
            self.assertEqual(command[command.index("-pattern_type") + 1], "none")
            self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file")
            self.assertEqual(command[command.index("-i") + 1], str(image))

    def test_bgm_m4a_uses_the_hardened_mov_policy(self) -> None:
        payload = {
            "format": {"duration": "2"},
            "streams": [
                {
                    "codec_type": "audio",
                    "sample_rate": "48000",
                    "channels": 2,
                    "duration": "2",
                }
            ],
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            bgm = root / "music.m4a"
            bgm.touch()
            config = {"bgm": {"file": "music.m4a"}}
            warnings: list[str] = []
            with mock.patch.object(
                builder, "require_command", return_value="ffprobe"
            ), mock.patch.object(
                builder.subprocess, "run", return_value=completed
            ) as run:
                prepared = builder.prepare_bgm(
                    config,
                    project_root=root,
                    fps=Fraction(30),
                    warnings=warnings,
                    restrict_to_project_root=True,
                )

            self.assertIsNotNone(prepared)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-f") + 1], "mov")
            self.assertEqual(command[command.index("-enable_drefs") + 1], "0")
            self.assertEqual(command[command.index("-use_absolute_path") + 1], "0")

    def test_external_diagnostic_strips_terminal_commands_and_is_bounded(self) -> None:
        raw = (
            "\x1b]8;;file:///private/secret.mov\x07linked\x1b]8;;\x07 "
            "\x1b[31mred\x1b[0m\nmetadata\x00\x07 "
            + ("A" * (builder.EXTERNAL_DIAGNOSTIC_MAX_CHARS * 2))
        )

        cleaned = builder.sanitize_external_diagnostic(raw)

        self.assertNotIn("\x1b", cleaned)
        self.assertNotIn("file:///private/secret.mov", cleaned)
        self.assertTrue(
            all(not (ord(char) < 32 or 127 <= ord(char) <= 159) for char in cleaned)
        )
        self.assertLessEqual(len(cleaned), builder.EXTERNAL_DIAGNOSTIC_MAX_CHARS)
        self.assertIn("linked red metadata", cleaned)
        self.assertTrue(cleaned.endswith("…(이하 생략)"))

    def test_ffprobe_error_uses_sanitized_diagnostic(self) -> None:
        malicious = "bad\x1b]0;owned\x07\n\x1b[31mmedia\x1b[0m\x00"
        failure = subprocess.CalledProcessError(
            returncode=1,
            cmd=["ffprobe"],
            stderr=malicious,
        )
        with tempfile.TemporaryDirectory() as temp_text:
            media = Path(temp_text) / "clip.mp4"
            media.touch()
            with mock.patch.object(
                builder, "require_command", return_value="ffprobe"
            ), mock.patch.object(builder.subprocess, "run", side_effect=failure):
                with self.assertRaises(builder.BuildError) as raised:
                    builder.probe_media(media)

        message = str(raised.exception)
        self.assertNotIn("\x1b", message)
        self.assertNotIn("owned", message)
        self.assertIn("bad media", message)


if __name__ == "__main__":
    unittest.main()
