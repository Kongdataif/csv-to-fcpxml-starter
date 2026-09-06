"""Regression coverage for the FCPXML 1.14 title child-order import failure.

The optional full-DTD checks use FCPXML_DTD, supplied and verified by CI.
No user footage, generated project, or DTD copy is stored in the repository.
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


class ProjectFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        (self.project / "Media").mkdir()
        (self.project / "Media" / "sample.mov").write_bytes(b"mock media; not video")
        self.plan = self.project / "timeline.csv"
        self.write_plan(["First <title> & text", "Second\nline"])
        # XML construction is the subject of these tests, not codec decoding.
        probe = patch.object(app, "probe", return_value=(
            Fraction(30), 640, 360, Fraction(30), True, 2, 48000))
        probe.start()
        self.addCleanup(probe.stop)

    def write_plan(self, titles):
        with self.plan.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(app.HEADERS)
            for start, end, title in zip((2, 13), (11, 22), titles):
                writer.writerow(["sample.mov", start, end, "", title, "사용"])

    def build(self, layout="landscape"):
        return app.build_project(self.project, layout, "fit")

    @staticmethod
    def put_transform_first(title):
        transform = title.find("adjust-transform")
        title.remove(transform)
        title.insert(0, transform)


class TitleXmlTests(ProjectFixture, unittest.TestCase):
    def test_generator_emits_dtd_order_in_both_layouts(self):
        for path in self.build("both"):
            root = ET.parse(path).getroot()
            titles = list(root.iter("title"))
            self.assertEqual(len(titles), 2)
            for title in titles:
                self.assertEqual([child.tag for child in title],
                                 ["text", "text-style-def", "adjust-transform"])
            app.validate_xml(path, *app.LAYOUTS[path.stem])

    def test_preserves_text_times_style_and_position(self):
        for path in self.build("both"):
            root = ET.parse(path).getroot()
            self.assertEqual(root.find("event/project/sequence").get("duration"), "18s")
            for index, title in enumerate(root.iter("title")):
                self.assertEqual(title.get("offset"), ("2s", "13s")[index])
                self.assertEqual(title.get("duration"), "9s")
                self.assertEqual(title.get("start"), "3600s")
                self.assertEqual(title.find("text/text-style").text,
                                 ("First <title> & text", "Second\nline")[index])
                style = title.find("text-style-def/text-style")
                self.assertEqual(style.get("fontSize"), "54" if path.stem == "portrait" else "44")
                self.assertEqual(title.find("adjust-transform").get("position"), "0 -37.5")

    def test_validator_rejects_original_transform_first_order(self):
        for path in self.build("both"):
            tree = ET.parse(path)
            self.put_transform_first(tree.getroot().find(".//title"))
            tree.write(path, encoding="utf-8", xml_declaration=True)
            with self.assertRaisesRegex(app.UserError, "타이틀 구성 오류"):
                app.validate_xml(path, *app.LAYOUTS[path.stem])

    def test_validator_checks_the_second_title_too(self):
        path = self.build()[0]
        tree = ET.parse(path)
        self.put_transform_first(list(tree.getroot().iter("title"))[1])
        tree.write(path, encoding="utf-8", xml_declaration=True)
        with self.assertRaisesRegex(app.UserError, "Title 02"):
            app.validate_xml(path, *app.LAYOUTS["landscape"])

    def test_validator_rejects_style_before_text(self):
        path = self.build()[0]
        tree = ET.parse(path)
        title = tree.getroot().find(".//title")
        style = title.find("text-style-def")
        title.remove(style)
        title.insert(0, style)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        with self.assertRaisesRegex(app.UserError, "타이틀 구성 오류"):
            app.validate_xml(path, *app.LAYOUTS["landscape"])

    def test_validator_rejects_missing_text_block(self):
        path = self.build()[0]
        tree = ET.parse(path)
        title = tree.getroot().find(".//title")
        title.remove(title.find("text"))
        tree.write(path, encoding="utf-8", xml_declaration=True)
        with self.assertRaisesRegex(app.UserError, "타이틀 구성 오류"):
            app.validate_xml(path, *app.LAYOUTS["landscape"])

    def test_no_title_rows_still_work(self):
        self.write_plan(["", ""])
        for path in self.build("both"):
            self.assertEqual(list(ET.parse(path).getroot().iter("title")), [])
            app.validate_xml(path, *app.LAYOUTS[path.stem])

    def test_bad_generated_title_cannot_replace_or_authorize_output(self):
        path = self.build()[0]
        previous = path.read_bytes()
        original = app.add_title

        def broken(parent, *args):
            original(parent, *args)
            self.put_transform_first(parent.find("title"))

        with patch.object(app, "add_title", side_effect=broken):
            with self.assertRaisesRegex(app.UserError, "타이틀 구성 오류"):
                self.build()
        self.assertEqual(path.read_bytes(), previous)
        with self.assertRaises(app.UserError):
            app.verified_result(self.project)


@unittest.skipUnless(os.environ.get("FCPXML_DTD"), "FCPXML_DTD is provided by CI")
class FullTitleDTDTests(ProjectFixture, unittest.TestCase):
    def validate(self, path):
        dtd = Path(os.environ["FCPXML_DTD"])
        self.assertTrue(dtd.is_file(), "The configured DTD must exist")
        self.assertIsNotNone(shutil.which("xmllint"), "xmllint is required for full DTD tests")
        return subprocess.run(["xmllint", "--nonet", "--noout", "--dtdvalid", str(dtd), str(path)],
                              capture_output=True, text=True, timeout=30)

    def test_full_1_14_dtd_accepts_both_generated_layouts(self):
        for path in self.build("both"):
            result = self.validate(path)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_1_14_dtd_reproduces_original_title_failure(self):
        path = self.build()[0]
        tree = ET.parse(path)
        self.put_transform_first(tree.getroot().find(".//title"))
        tree.write(path, encoding="utf-8", xml_declaration=True)
        result = self.validate(path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Element title content does not follow the DTD", result.stderr)


if __name__ == "__main__":
    unittest.main()
