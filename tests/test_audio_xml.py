"""Regression coverage for per-row audio decisions in imported FCPXML.

Media metadata and photo rendering are mocked so these checks do not depend on
FFmpeg or personal footage. Optional full-DTD checks use FCPXML_DTD.
"""
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run as app


class AudioProjectFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        (self.project / "Media").mkdir()
        self.channels = {"mono.mov": 1, "stereo.mov": 2,
                         "surround.mov": 6, "silent.mov": 0}
        for name in (*self.channels, "photo.png"):
            (self.project / "Media" / name).write_bytes(b"mock source media")
        self.plan = self.project / "timeline.csv"
        probe = patch.object(app, "probe", side_effect=self.probe)
        probe.start()
        self.addCleanup(probe.stop)
        render = patch.object(app, "render_image", side_effect=self.render_photo)
        render.start()
        self.addCleanup(render.stop)

    def probe(self, path):
        channels = self.channels[path.name]
        return (Fraction(30), 640, 360, Fraction(30), bool(channels),
                channels, 48000 if channels else 0)

    @staticmethod
    def render_photo(clip, output, width, height, fit):
        media = output / "media"
        media.mkdir(parents=True, exist_ok=True)
        path = media / "photo.mp4"
        path.write_bytes(b"mock rendered photo")
        clip.width, clip.height = width, height
        clip.source_fps, clip.media_duration = app.FPS, clip.duration
        return path

    def write_plan(self, rows):
        with self.plan.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(app.HEADERS)
            writer.writerows(rows)

    def build(self, layout="portrait"):
        return app.build_project(self.project, layout, "fit")

    @staticmethod
    def timeline_clips(root):
        return root.findall("event/project/sequence/spine/asset-clip")

    @staticmethod
    def source_channels(components):
        return [int(channel.strip())
                for component in components
                for channel in component.get("srcCh", "").split(",")
                if channel.strip()]

    def assert_muted_components(self, clip, channels):
        components = clip.findall("audio-channel-source")
        self.assertEqual(sorted(self.source_channels(components)),
                         list(range(1, channels + 1)))
        for component in components:
            self.assertEqual(component.get("active"), "0")
            self.assertEqual(component.get("role"), "dialogue")
        # Disabling components must not also lower the editable clip's volume.
        self.assertIsNone(clip.find("adjust-volume"))
        return components

    def write_channel_plan(self):
        self.write_plan([
            ["mono.mov", "2", "7", "", "Mono title", "끄기"],
            ["stereo.mov", "3", "8", "", "Stereo title", "끄기"],
            ["surround.mov", "4", "9", "", "Surround title", "끄기"],
            ["stereo.mov", "10", "15", "", "Audible title", "사용"],
            ["silent.mov", "0", "2", "", "", "끄기"],
            ["photo.png", "", "", "2", "Photo title", "끄기"],
        ])


class AudioXmlTests(AudioProjectFixture, unittest.TestCase):
    def test_mixed_rows_reuse_source_without_muting_other_occurrences(self):
        self.write_plan([
            ["stereo.mov", "2", "7", "", "First audible", "사용"],
            ["stereo.mov", "10", "15", "", "Muted occurrence", "끄기"],
            ["stereo.mov", "20", "25", "", "Last audible", "사용"],
        ])
        for path in self.build("both"):
            root = ET.parse(path).getroot()
            assets = root.findall("resources/asset")
            self.assertEqual(len({asset.find("media-rep").get("src") for asset in assets}), 1)
            # Muting a timeline occurrence must not falsify source capabilities.
            for asset in assets:
                self.assertEqual(asset.get("hasAudio"), "1")
                self.assertEqual(asset.get("audioChannels"), "2")
            clips = self.timeline_clips(root)
            self.assertEqual([clip.get("srcEnable") for clip in clips], ["all", "video", "all"])
            self.assertEqual([clip.get("start") for clip in clips], ["2s", "10s", "20s"])
            self.assertEqual([clip.get("offset") for clip in clips], ["0s", "5s", "10s"])
            self.assertEqual([clip.get("duration") for clip in clips], ["5s"] * 3)
            self.assert_muted_components(clips[1], 2)
            for clip in (clips[0], clips[2]):
                self.assertIsNone(clip.find(".//mute"))
                for component in clip.findall("audio-channel-source"):
                    self.assertEqual(component.get("enabled", "1"), "1")
                    self.assertEqual(component.get("active", "1"), "1")

    def test_muted_components_cover_mono_stereo_and_surround_channels(self):
        self.write_channel_plan()
        for path in self.build("both"):
            root = ET.parse(path).getroot()
            for clip, channels in zip(self.timeline_clips(root), (1, 2, 6)):
                with self.subTest(layout=path.stem, channels=channels):
                    components = self.assert_muted_components(clip, channels)
                    # Audio components must follow any connected titles.
                    children = list(clip)
                    for component in components:
                        self.assertGreater(children.index(component), children.index(clip.find("title")))

    def test_muted_clip_without_title_still_disables_components(self):
        self.write_plan([["mono.mov", "2", "7", "", "", "끄기"]])
        clip = self.timeline_clips(ET.parse(self.build()[0]).getroot())[0]
        self.assertIsNone(clip.find("title"))
        self.assert_muted_components(clip, 1)

    def test_sound_values_are_evaluated_for_each_row(self):
        sounds = ("사용", "끄기", "", "예", "아니오", "true", "false", "1", "0")
        self.write_plan([["stereo.mov", "2", "7", "", "", sound]
                         for sound in sounds])
        clips = app.load_clips(self.project, self.plan)
        self.assertEqual([clip.include_audio for clip in clips],
                         [True, False, True, True, False, True, False, True, False])
        self.assertTrue(all(clip.has_audio for clip in clips))

    def test_silent_videos_and_photos_have_no_audio_components(self):
        self.write_plan([
            [name, "", "", "2" if name.endswith(".png") else "", "", sound]
            for name in ("silent.mov", "photo.png")
            for sound in ("사용", "끄기")
        ])
        for path in self.build("both"):
            root = ET.parse(path).getroot()
            for asset in root.findall("resources/asset"):
                self.assertIsNone(asset.get("hasAudio"))
                self.assertIsNone(asset.get("audioChannels"))
            for clip in self.timeline_clips(root):
                self.assertEqual(clip.get("srcEnable"), "video")
                self.assertEqual(clip.findall("audio-channel-source"), [])
                self.assertIsNone(clip.find("adjust-volume"))
                self.assertIsNone(clip.find(".//mute"))

    def test_enabled_audio_keeps_default_level(self):
        self.write_plan([["stereo.mov", "2", "7", "", "", sound]
                         for sound in ("사용", "")])
        root = ET.parse(self.build()[0]).getroot()
        for clip in self.timeline_clips(root):
            self.assertEqual(clip.get("srcEnable"), "all")
            self.assertIsNone(clip.find("adjust-volume"))
            self.assertIsNone(clip.find(".//mute"))
            for component in clip.findall("audio-channel-source"):
                self.assertEqual(component.get("enabled", "1"), "1")
                self.assertEqual(component.get("active", "1"), "1")


@unittest.skipUnless(os.environ.get("FCPXML_DTD"), "FCPXML_DTD is provided by CI")
class FullAudioDTDTests(AudioProjectFixture, unittest.TestCase):
    def validate(self, path):
        dtd = Path(os.environ["FCPXML_DTD"])
        self.assertTrue(dtd.is_file(), "The configured DTD must exist")
        self.assertIsNotNone(shutil.which("xmllint"), "xmllint is required for full DTD tests")
        # libxml expects a URI here; the installed Final Cut app path has spaces.
        return subprocess.run(["xmllint", "--nonet", "--noout", "--dtdvalid", dtd.resolve().as_uri(), str(path)],
                              capture_output=True, text=True, timeout=30)

    def test_full_1_14_dtd_accepts_audio_components_in_both_layouts(self):
        self.write_channel_plan()
        for path in self.build("both"):
            result = self.validate(path)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_1_14_dtd_rejects_audio_components_before_titles(self):
        self.write_channel_plan()
        path = self.build()[0]
        tree = ET.parse(path)
        clip = self.timeline_clips(tree.getroot())[0]
        component = clip.find("audio-channel-source")
        self.assertIsNotNone(component)
        clip.remove(component)
        clip.insert(list(clip).index(clip.find("title")), component)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        result = self.validate(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Element asset-clip content does not follow the DTD", result.stderr)


if __name__ == "__main__":
    unittest.main()
