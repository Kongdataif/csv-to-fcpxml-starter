from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.configure_github import configure_repository


REPO_ROOT = Path(__file__).resolve().parents[1]


class ConfigureGithubTests(unittest.TestCase):
    def make_copy(self, root: Path) -> None:
        (root / "notebooks").mkdir()
        shutil.copy2(REPO_ROOT / "README.md", root / "README.md")
        shutil.copy2(
            REPO_ROOT / "notebooks" / "CSV_to_FCPXML_Colab.ipynb",
            root / "notebooks" / "CSV_to_FCPXML_Colab.ipynb",
        )

    def test_updates_readme_badge_and_notebook_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            self.make_copy(root)
            url, ref = configure_repository(
                root,
                owner="example-owner",
                repository="csv-to-fcpxml-starter",
                ref="v0.6.0",
            )

            self.assertEqual(url, "https://github.com/example-owner/csv-to-fcpxml-starter.git")
            self.assertEqual(ref, "v0.6.0")
            readme = (root / "README.md").read_text(encoding="utf-8")
            self.assertIn("Open In Colab", readme)
            self.assertIn("example-owner/csv-to-fcpxml-starter/blob/v0.6.0", readme)

            notebook = json.loads(
                (root / "notebooks" / "CSV_to_FCPXML_Colab.ipynb").read_text(
                    encoding="utf-8"
                )
            )
            source = "".join(
                line
                for cell in notebook["cells"]
                if cell.get("cell_type") == "code"
                for line in cell.get("source", [])
            )
            self.assertIn(f'REPO_URL = "{url}"', source)
            self.assertIn('REPO_REF = "v0.6.0"', source)

    def test_rejects_owner_with_path_characters_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_text:
            root = Path(temp_text)
            self.make_copy(root)
            original = (root / "README.md").read_text(encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "GitHub ID"):
                configure_repository(
                    root,
                    owner="bad/owner",
                    repository="csv-to-fcpxml-starter",
                    ref="v0.6.0",
                )
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
