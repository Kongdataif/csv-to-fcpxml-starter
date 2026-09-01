from __future__ import annotations

import ast
import hashlib
import json
import re
import unittest
from pathlib import Path


class ColabNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = (
            Path(__file__).resolve().parents[1]
            / "notebooks"
            / "CSV_to_FCPXML_Colab.ipynb"
        )
        cls.notebook = json.loads(cls.path.read_text(encoding="utf-8"))
        cls.code = "\n\n".join(
            "".join(cell.get("source", []))
            for cell in cls.notebook["cells"]
            if cell.get("cell_type") == "code"
        )
        cls.markdown = "\n\n".join(
            "".join(cell.get("source", []))
            for cell in cls.notebook["cells"]
            if cell.get("cell_type") == "markdown"
        )
        cls.form_code = "\n\n".join(
            "".join(cell.get("source", []))
            for cell in cls.notebook["cells"]
            if cell.get("cell_type") == "code"
            and cell.get("metadata", {}).get("cellView") == "form"
        )
        cls.template_path = cls.path.parents[1] / "templates" / "simple_timeline.csv"

    def test_notebook_is_valid_v4_and_all_code_parses(self) -> None:
        self.assertEqual(self.notebook["nbformat"], 4)
        self.assertGreaterEqual(len(self.notebook["cells"]), 12)
        ast.parse(self.code)

    def test_beginner_form_defaults_and_korean_schema_are_explicit(self) -> None:
        self.assertIn('PROJECT_NAME = "MyVideo"  # @param', self.code)
        self.assertIn(
            'OUTPUT_FORMAT = "portrait"  # @param ["portrait", "landscape", "both"]',
            self.code,
        )
        self.assertIn('FPS = "30"  # @param', self.code)
        self.assertIn('SUBTITLE_MODE = "title"  # @param', self.code)
        self.assertIn('EXPORT_SRT = True  # @param', self.code)
        self.assertIn('DEFAULT_PHOTO_DURATION = 3.0  # @param', self.code)
        self.assertIn('USE_SEPARATE_SUBTITLES_CSV = False  # @param', self.code)
        default_header = (
            "파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리"
        )
        self.assertIn(default_header, self.markdown)
        self.assertEqual(
            self.template_path.read_text(encoding="utf-8-sig").splitlines()[0],
            default_header,
        )
        self.assertIn("기획표에 적은 행 순서가 곧 편집 순서", self.markdown)
        self.assertIn("`순서`, `화면 맞춤`, `메모`", self.markdown)
        for value in ("전체 보이기", "화면 채우기", "자동 맞춤 안 함"):
            self.assertIn(value, self.markdown)
        self.assertIn("원본 영상에서 12초 지점부터 16초 지점까지", self.markdown)
        self.assertIn("Final Cut Pro가 설치된 Mac", self.markdown)
        self.assertIn("최신 Chrome, Edge 또는 Safari", self.markdown)
        self.assertIn("로컬 가상환경 실행을 권장", self.markdown)

    def test_timeline_headers_accept_default_extended_and_known_optional_subsets(self) -> None:
        tree = ast.parse(self.code)

        def literal_assignment(name: str):
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                    return ast.literal_eval(node.value)
            self.fail(f"assignment not found: {name}")

        default_headers = literal_assignment("DEFAULT_TIMELINE_HEADERS")
        extended_headers = literal_assignment("EXTENDED_TIMELINE_HEADERS")
        self.assertEqual(
            default_headers,
            [
                "파일",
                "영상 원본 시작",
                "영상 원본 끝",
                "사진 표시 시간(초)",
                "화면 자막",
                "소리",
            ],
        )
        self.assertEqual(
            extended_headers,
            [
                "순서",
                *default_headers,
                "화면 맞춤",
                "메모",
            ],
        )
        validation_nodes = []
        validation_names = {
            "DEFAULT_TIMELINE_HEADERS",
            "EXTENDED_TIMELINE_HEADERS",
            "KNOWN_TIMELINE_HEADERS",
            "REQUIRED_TIMELINE_HEADERS",
        }
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in validation_names
                for target in node.targets
            ):
                validation_nodes.append(node)
            elif isinstance(node, ast.FunctionDef) and node.name == "validate_timeline_headers":
                validation_nodes.append(node)
        namespace = {}
        validation_module = ast.fix_missing_locations(
            ast.Module(body=validation_nodes, type_ignores=[])
        )
        exec(compile(validation_module, str(self.path), "exec"), namespace)
        validate = namespace["validate_timeline_headers"]
        self.assertEqual(validate(default_headers), default_headers)
        self.assertEqual(validate(extended_headers), extended_headers)
        self.assertEqual(validate(["파일", "메모"]), ["파일", "메모"])
        for invalid_headers in (
            ["파일", "파일"],
            ["파일", "알 수 없는 열"],
            ["화면 자막", "메모"],
        ):
            with self.assertRaises(ValueError):
                validate(invalid_headers)
        self.assertIn('REQUIRED_TIMELINE_HEADERS = {"파일"}', self.code)
        self.assertIn("unknown_headers = sorted(set(actual_headers) - KNOWN_TIMELINE_HEADERS)", self.code)
        self.assertIn("duplicate_headers = sorted", self.code)
        self.assertIn('has_order_column = "순서" in actual_headers', self.code)
        self.assertIn('if has_order_column:', self.code)
        self.assertIn('else TIMELINE_ROWS', self.code)

    def test_source_is_pinned_and_only_developer_fallback_uses_starter_zip(self) -> None:
        repo_url_match = re.search(r'^REPO_URL = "([^"]*)"$', self.code, re.MULTILINE)
        self.assertIsNotNone(repo_url_match)
        repo_url = repo_url_match.group(1)
        if repo_url:
            self.assertRegex(
                repo_url,
                r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$",
            )
        self.assertRegex(self.code, r'REPO_REF = "v\d+\.\d+\.\d+"')
        self.assertNotIn("REPO_URL", self.form_code)
        self.assertNotIn("REPO_REF", self.form_code)
        self.assertNotIn("SOURCE_SHA256", self.form_code)
        developer_cells = [
            cell
            for cell in self.notebook["cells"]
            if cell.get("cell_type") == "code"
            and re.search(r"^REPO_URL\s*=", "".join(cell.get("source", [])), re.MULTILINE)
        ]
        self.assertEqual(len(developer_cells), 1)
        self.assertTrue(developer_cells[0].get("metadata", {}).get("collapsed"))
        self.assertNotEqual(developer_cells[0].get("metadata", {}).get("cellView"), "form")
        self.assertNotIn("# @param", "".join(developer_cells[0].get("source", [])))
        self.assertIn('"fetch", "--quiet", "--depth", "1", "origin", repository_ref', self.code)
        self.assertIn('"checkout", "--quiet", "--detach", "FETCH_HEAD"', self.code)
        self.assertIn('"rev-parse", "HEAD"', self.code)
        for source_name in (
            "make_xml.py",
            "make_xml_input.py",
            "csv_to_fcpxml.py",
            "simple_timeline.py",
            "spreadsheet_input.py",
            "preview_report.py",
            "scripts/validate_fcpxml.py",
        ):
            self.assertIn(f'"{source_name}"', self.code)
        self.assertIn("actual_sha256 = sha256_file(source_path)", self.code)
        self.assertIn("if actual_sha256 != expected_sha256:", self.code)
        self.assertIn("EXECUTION_SOURCE_FILES = (", self.code)
        self.assertIn('WORKSPACE / "verified_execution"', self.code)
        self.assertIn("set(SOURCE_SHA256) != set(EXECUTION_SOURCE_FILES)", self.code)
        self.assertIn("shutil.copyfile(source_path, destination)", self.code)
        self.assertIn("SPREADSHEET_INPUT_PATH = require_regular_file_inside(", self.code)
        self.assertIn("importlib.util.spec_from_file_location(", self.code)
        self.assertIn("spreadsheet_spec.loader.exec_module(spreadsheet_module)", self.code)
        self.assertIn("PlanInputError = spreadsheet_module.PlanInputError", self.code)
        self.assertIn(
            "decode_uploaded_plan = spreadsheet_module.decode_uploaded_plan", self.code
        )
        self.assertLess(
            self.code.index("shutil.copyfile(source_path, destination)"),
            self.code.index("SPREADSHEET_INPUT_PATH = require_regular_file_inside("),
        )
        placeholders = (
            "__FINAL_SHA256_MAKE_XML__",
            "__FINAL_SHA256_MAKE_XML_INPUT__",
            "__FINAL_SHA256_CSV_TO_FCPXML__",
            "__FINAL_SHA256_SIMPLE_TIMELINE__",
            "__FINAL_SHA256_SPREADSHEET_INPUT__",
            "__FINAL_SHA256_PREVIEW_REPORT__",
            "__FINAL_SHA256_VALIDATE_FCPXML__",
        )
        if "SOURCE_HASHES_READY = False" in self.code:
            # 통합 중에는 일곱 자리표시자가 모두 있어야 부분 치환을 놓치지 않는다.
            for placeholder in placeholders:
                self.assertIn(placeholder, self.code)
        else:
            # 공개 릴리스에서는 ready=True와 실제 64자리 해시만 허용한다.
            self.assertIn("SOURCE_HASHES_READY = True", self.code)
            for placeholder in placeholders:
                self.assertNotIn(placeholder, self.code)
            repository_root = self.path.parents[1]
            for source_name in (
                "make_xml.py",
                "make_xml_input.py",
                "csv_to_fcpxml.py",
                "simple_timeline.py",
                "spreadsheet_input.py",
                "preview_report.py",
                "scripts/validate_fcpxml.py",
            ):
                match = re.search(
                    rf'"{re.escape(source_name)}": "([0-9a-f]{{64}})"', self.code
                )
                self.assertIsNotNone(match, source_name)
                actual = hashlib.sha256((repository_root / source_name).read_bytes()).hexdigest()
                self.assertEqual(match.group(1), actual, source_name)
        self.assertIn("[개발자 전용 fallback]", self.code)
        self.assertIn("safe_extract_starter_zip", self.code)
        self.assertNotIn("input_project.zip", self.code)
        self.assertNotIn("project.colab.json", self.code)

    def test_direct_upload_staging_has_filename_and_product_limits(self) -> None:
        self.assertIn('timeline_upload = direct_upload(', self.code)
        self.assertIn('subtitle_upload = direct_upload(', self.code)
        self.assertIn('media_upload = direct_upload(', self.code)
        self.assertIn(
            'timeline_original_name, timeline_payload, kind="timeline", '
            'max_rows=MAX_TIMELINE_ROWS',
            self.code,
        )
        self.assertIn(
            'subtitle_original_name, subtitle_payload, kind="subtitles", '
            'max_rows=MAX_SUBTITLE_ROWS',
            self.code,
        )
        self.assertIn("except PlanInputError as error:", self.code)
        self.assertIn(
            "save_uploaded_bytes(timeline_canonical_bytes, TIMELINE_PATH, replace=True)",
            self.code,
        )
        self.assertIn(
            "save_uploaded_bytes(subtitle_canonical_bytes, SUBTITLES_PATH, replace=True)",
            self.code,
        )
        self.assertNotIn('suffix.lower() != ".csv"', self.code)
        self.assertNotIn('suffix.lower() == ".numbers"', self.code)
        self.assertIn("`.csv` 또는 `.xlsx`", self.markdown)
        self.assertNotIn("drive.mount", self.code)
        self.assertNotIn("gdown", self.code)
        self.assertIn('if USE_SEPARATE_SUBTITLES_CSV:', self.code)
        self.assertIn("자막 입력이 두 곳에 있습니다", self.code)
        self.assertIn('TIMELINE_PATH = PROJECT_ROOT / "timeline.csv"', self.code)
        self.assertIn('SUBTITLES_PATH = PROJECT_ROOT / "subtitles.csv"', self.code)
        self.assertIn('MEDIA_DIR = PROJECT_ROOT / "Media"', self.code)
        self.assertIn("safe_uploaded_basename", self.code)
        self.assertIn('unicodedata.normalize("NFC", name).casefold()', self.code)
        self.assertIn("MAX_MEDIA_FILES", self.code)
        self.assertIn("MAX_SINGLE_MEDIA_BYTES", self.code)
        self.assertIn("MAX_TOTAL_UPLOAD_BYTES", self.code)
        self.assertIn("MAX_FILENAME_BYTES", self.code)
        self.assertIn('len(name.encode("utf-8")) > MAX_FILENAME_BYTES', self.code)
        self.assertIn("def utf8_prefix(value, max_bytes):", self.code)
        self.assertIn("all_input_bytes", self.code)
        self.assertIn("has_control_character", self.code)
        self.assertIn('if "/" in name or "\\\\" in name', self.code)
        self.assertIn("timeout=60", self.code)
        self.assertIn("except subprocess.TimeoutExpired", self.code)
        self.assertIn("미디어 검사 시간이 60초를 넘었습니다", self.code)

    def test_spreadsheet_adapter_owns_xlsx_parsing_and_upload_budget_uses_originals(self) -> None:
        for adapter_detail in (
            "MAX_XLSX_",
            "datetime_time",
            "timedelta",
            "from datetime import date,",
            "import math",
        ):
            self.assertNotIn(adapter_detail, self.code)
        self.assertEqual(self.code.count("decode_uploaded_plan("), 2)
        self.assertIn("timeline_source_description", self.code)
        self.assertIn("subtitle_source_description", self.code)
        self.assertIn("SUBTITLE_BYTES = len(subtitle_payload)", self.code)
        self.assertIn(
            "all_input_bytes = len(timeline_payload) + SUBTITLE_BYTES + media_total_bytes",
            self.code,
        )
        self.assertIn("Numbers", self.markdown)
        self.assertIn("다음으로 내보내기 → Excel", self.markdown)

    def test_plan_preview_is_escaped_and_confirmed_before_media_upload(self) -> None:
        self.assertIn("import html", self.code)
        self.assertIn("from IPython.display import HTML, display", self.code)
        self.assertIn("def display_plan_preview(", self.code)
        self.assertIn("html.escape(", self.code)
        self.assertIn('replace("\\n", "<br>")', self.code)
        self.assertIn('"타임라인 기획표 확인"', self.code)
        self.assertIn('"정밀 자막 기획표 확인"', self.code)
        self.assertIn("정확한 폰트·크기·위치·윤곽선", self.code)
        self.assertIn("preview_confirmation = input(", self.code)
        self.assertLessEqual(self.code.count("PREVIEW_MAX_ROWS = 20"), 1)
        self.assertLess(
            self.code.index("preview_confirmation = input("),
            self.code.index('media_upload = direct_upload('),
        )
        self.assertNotIn('bytes(timeline_payload).decode("utf-8-sig")', self.code)
        self.assertNotIn('bytes(subtitle_payload).decode("utf-8-sig")', self.code)

    def test_build_uses_make_xml_and_rejects_absolute_media_uris(self) -> None:
        self.assertIn('REPO_DIR / "make_xml.py"', self.code)
        self.assertIn("sys.executable, str(MAKE_XML), str(PROJECT_ROOT)", self.code)
        self.assertIn('"--photo-duration", str(DEFAULT_PHOTO_DURATION)', self.code)
        self.assertIn('"--subtitle-mode", SUBTITLE_MODE', self.code)
        self.assertIn('"--layout", OUTPUT_FORMAT', self.code)
        self.assertIn(
            'if OUTPUT_FORMAT not in {"portrait", "landscape", "both"}:',
            self.code,
        )
        self.assertIn('"--validate-only"', self.code)
        self.assertIn('"--require-relative"', self.code)
        self.assertIn('forbidden in (str(WORKSPACE), "/content/")', self.code)
        self.assertIn("parsed.scheme", self.code)
        self.assertNotIn("drive.mount", self.code)
        self.assertNotIn("share=True", self.code)
        self.assertNotIn("gradio", self.code.lower())

    def test_dual_format_build_is_separated_and_verified_from_actual_xml(self) -> None:
        self.assertIn('"directory": "vertical_9x16"', self.code)
        self.assertIn('"directory": "horizontal_16x9"', self.code)
        self.assertIn('"width": 1080, "height": 1920', self.code)
        self.assertIn('"width": 1920, "height": 1080', self.code)
        self.assertIn(
            'selected_layouts = ["portrait", "landscape"] if OUTPUT_FORMAT == "both"',
            self.code,
        )
        self.assertIn('xml_files = sorted(GENERATED.rglob("*.fcpxml"))', self.code)
        self.assertIn(
            "actual_target_directories != expected_target_directories", self.code
        )
        self.assertIn('sequence = root.find(".//project/sequence")', self.code)
        self.assertIn('root.findall("./resources/format")', self.code)
        self.assertIn('EXPECTED_FRAME_DURATIONS[str(FPS)]', self.code)
        self.assertIn('"targets": manifest_targets', self.code)
        self.assertIn('"schema_version": 2', self.code)
        self.assertIn('"fcpxml_files": [', self.code)
        self.assertIn("실제 FCPXML 프로젝트 format", self.code)
        self.assertIn("한 번 올린 파일로 세로와 가로를 순서대로 생성", self.markdown)
        self.assertIn("방향별 폴더로 분리", self.markdown)

    def test_download_zip_is_allowlisted_and_hash_manifested(self) -> None:
        self.assertIn(
            'ALLOWED_RESULT_SUFFIXES = {".fcpxml", ".srt", ".txt", ".json"}',
            self.code,
        )
        self.assertIn('relative.parts[0] not in expected_target_directories', self.code)
        self.assertIn('relative.parts[1] != ".build_media"', self.code)
        self.assertIn("EXECUTABLE_OR_SCRIPT_SUFFIXES", self.code)
        self.assertIn('"relative_path": relative_path', self.code)
        self.assertIn('"target": path.relative_to(GENERATED).parts[0]', self.code)
        self.assertIn('"size_bytes": path.stat().st_size', self.code)
        self.assertIn('"sha256": sha256_file(path)', self.code)
        self.assertIn('archive.write(MANIFEST_PATH, "manifest.json")', self.code)
        self.assertIn("archive.testzip()", self.code)
        self.assertIn("safe_result_name = utf8_prefix(safe_result_name, 180)", self.code)
        self.assertIn("다운로드 파일 목록 · 크기 · SHA-256", self.code)
        self.assertLess(
            self.code.index('print("다운로드 파일 목록 · 크기 · SHA-256")'),
            self.code.index("files.download(str(RESULT_ZIP))"),
        )
        self.assertIn("런타임 → 연결 해제 및 런타임 삭제", self.markdown)


if __name__ == "__main__":
    unittest.main()
