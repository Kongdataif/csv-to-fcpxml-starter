from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import create_project
from scripts.validate_fcpxml import validate


class ScaffoldTests(unittest.TestCase):
    def test_create_project_builds_expected_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            target = Path(temp_text) / "My Portrait"
            result = create_project.main([str(target), "--portrait", "--with-captions"])
            self.assertEqual(result, 0)
            self.assertTrue((target / "Media").is_dir())
            self.assertTrue((target / "Audio").is_dir())
            self.assertTrue((target / "Docs" / "captions.csv").is_file())
            self.assertTrue((target / "timeline.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertTrue(
                (target / "Docs" / "captions.csv").read_bytes().startswith(b"\xef\xbb\xbf")
            )
            config = json.loads((target / "project.json").read_text(encoding="utf-8"))
            self.assertEqual((config["width"], config["height"]), (1080, 1920))
            self.assertEqual(config["captions"]["file"], "Docs/captions.csv")

    def test_create_project_defaults_new_subtitles_to_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            target = Path(temp_text) / "My Titles"
            result = create_project.main([str(target), "--portrait", "--with-subtitles"])
            self.assertEqual(result, 0)
            self.assertTrue((target / "Docs" / "subtitles.csv").is_file())
            self.assertTrue((target / "timeline.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertTrue(
                (target / "Docs" / "subtitles.csv").read_bytes().startswith(b"\xef\xbb\xbf")
            )
            config = json.loads((target / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(config["subtitles"]["mode"], "title")
            self.assertTrue(config["subtitles"]["srt"])
            self.assertEqual(config["captions"], {})

    def test_nonempty_target_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            target = Path(temp_text) / "existing"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            result = create_project.main([str(target)])
            self.assertEqual(result, 2)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


class ValidatorTests(unittest.TestCase):
    def test_missing_relative_media_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            path = Path(temp_text) / "test.fcpxml"
            path.write_text(
                '<?xml version="1.0"?><fcpxml version="1.14"><resources>'
                '<asset id="r1"><media-rep kind="original-media" src="./missing.mov"/></asset>'
                '</resources><event><project><sequence><spine><asset-clip ref="r1"/></spine>'
                '</sequence></project></event></fcpxml>',
                encoding="utf-8",
            )
            errors = validate(path, check_media=True)
            self.assertTrue(any("참조 미디어가 없습니다" in error for error in errors))

    def test_portable_mode_rejects_absolute_and_outside_media(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            workspace = Path(temp_text)
            project = workspace / "project"
            generated = project / "Generated"
            generated.mkdir(parents=True)
            outside = workspace / "outside.mov"
            outside.touch()
            path = generated / "test.fcpxml"
            path.write_text(
                '<?xml version="1.0"?><fcpxml version="1.14"><resources>'
                f'<asset id="r1"><media-rep kind="original-media" src="{outside.as_uri()}"/></asset>'
                '<asset id="r2"><media-rep kind="original-media" src="../../outside.mov"/></asset>'
                '</resources><event><project><sequence><spine><asset-clip ref="r1"/></spine>'
                '</sequence></project></event></fcpxml>',
                encoding="utf-8",
            )
            errors = validate(
                path,
                check_media=True,
                require_relative=True,
                project_root=project,
            )
            self.assertTrue(any("상대 URI가 아닌" in error for error in errors))
            self.assertTrue(any("프로젝트 폴더 밖" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
