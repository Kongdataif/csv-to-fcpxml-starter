from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VsCodeTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(
            (ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8")
        )
        cls.tasks = {task["label"]: task for task in cls.payload["tasks"]}

    def test_beginner_tasks_match_the_v06_make_xml_cli(self) -> None:
        expected = {
            "1. 세로·가로 입력 검사": ["--layout", "both", "--validate-only"],
            "2. 세로·가로 미리보기": ["--layout", "both", "--preview-only"],
            "3. 세로·가로 XML 만들기 (추천)": ["--layout", "both"],
            "4. 세로 9:16 XML 만들기": ["--layout", "portrait"],
            "5. 세로 9:16 만들고 Final Cut에서 열기": [
                "--layout",
                "portrait",
                "--open",
            ],
            "6. 가로 16:9 XML 만들기": ["--layout", "landscape"],
            "7. 가로 16:9 만들고 Final Cut에서 열기": [
                "--layout",
                "landscape",
                "--open",
            ],
        }
        for label, tail in expected.items():
            with self.subTest(label=label):
                task = self.tasks[label]
                self.assertEqual(
                    task["command"], "${workspaceFolder}/.venv/bin/python"
                )
                self.assertEqual(
                    task["args"],
                    ["make_xml.py", "${input:projectDir}", *tail],
                )

    def test_there_is_one_default_build_and_unique_labels(self) -> None:
        task_list = self.payload["tasks"]
        labels = [task["label"] for task in task_list]
        self.assertEqual(len(labels), len(set(labels)))
        defaults = [
            task
            for task in task_list
            if task.get("group", {}).get("isDefault") is True
        ]
        self.assertEqual(
            [task["label"] for task in defaults],
            ["3. 세로·가로 XML 만들기 (추천)"],
        )

    def test_manual_xml_default_uses_the_profiled_output_path(self) -> None:
        inputs = {item["id"]: item for item in self.payload["inputs"]}
        self.assertEqual(
            inputs["xmlPath"]["default"],
            "projects/my-first-video/Generated/vertical_9x16/"
            "my-first-video_vertical_9x16_with_titles.fcpxml",
        )
        self.assertIn("timeline.xlsx", inputs["projectDir"]["description"])


if __name__ == "__main__":
    unittest.main()
