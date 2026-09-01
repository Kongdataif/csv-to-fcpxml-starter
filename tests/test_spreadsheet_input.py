from __future__ import annotations

import csv
import io
import stat
import unittest
import warnings
import zipfile
import zlib
from pathlib import Path
from unittest import mock
from xml.sax.saxutils import escape, quoteattr

import spreadsheet_input as subject


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def inline_cell(reference: str, value: str, *, style: int | None = None) -> str:
    style_attr = "" if style is None else f' s="{style}"'
    return (
        f'<c r="{reference}" t="inlineStr"{style_attr}>'
        f'<is><t xml:space="preserve">{escape(value)}</t></is></c>'
    )


def number_cell(reference: str, value: str, *, style: int | None = None) -> str:
    style_attr = "" if style is None else f' s="{style}"'
    return f'<c r="{reference}"{style_attr}><v>{escape(value)}</v></c>'


def typed_cell(reference: str, cell_type: str, value: str, *, extra: str = "") -> str:
    return f'<c r="{reference}" t="{cell_type}">{extra}<v>{escape(value)}</v></c>'


def worksheet_xml(rows: list[tuple[int, list[str]]], *, tail: str = "") -> str:
    body = "".join(
        f'<row r="{row_number}">{"".join(cells)}</row>'
        for row_number, cells in rows
    )
    return (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>{body}</sheetData>{tail}</worksheet>'
    )


def _base_parts(
    *,
    sheets: list[tuple[str, str, str]] | None = None,
    shared_strings: str | None = None,
    styles: str | None = None,
    workbook_relationships_extra: str = "",
    root_relationships_extra: str = "",
    content_types_extra: str = "",
) -> dict[str, bytes]:
    if sheets is None:
        sheets = [
            (
                "Sheet1",
                "visible",
                worksheet_xml(
                    [
                        (1, [inline_cell("A1", "파일"), inline_cell("B1", "화면 자막")]),
                        (2, [inline_cell("A2", "intro.mp4"), inline_cell("B2", "안녕하세요")]),
                    ]
                ),
            )
        ]

    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    ]
    workbook_sheet_nodes: list[str] = []
    workbook_rel_nodes: list[str] = []
    parts: dict[str, bytes] = {}
    for index, (name, state, xml) in enumerate(sheets, start=1):
        state_attr = "" if state == "visible" else f" state={quoteattr(state)}"
        workbook_sheet_nodes.append(
            f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"{state_attr}/>'
        )
        workbook_rel_nodes.append(
            f'<Relationship Id="rId{index}" '
            f'Type="{REL_NS}/worksheet" Target="worksheets/sheet{index}.xml"/>'
        )
        part_name = f"xl/worksheets/sheet{index}.xml"
        parts[part_name] = xml.encode("utf-8")
        overrides.append(
            f'<Override PartName="/{part_name}" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )

    next_rid = len(sheets) + 1
    if shared_strings is not None:
        parts["xl/sharedStrings.xml"] = shared_strings.encode("utf-8")
        workbook_rel_nodes.append(
            f'<Relationship Id="rId{next_rid}" Type="{REL_NS}/sharedStrings" '
            'Target="sharedStrings.xml"/>'
        )
        overrides.append(
            '<Override PartName="/xl/sharedStrings.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        )
        next_rid += 1
    if styles is not None:
        parts["xl/styles.xml"] = styles.encode("utf-8")
        workbook_rel_nodes.append(
            f'<Relationship Id="rId{next_rid}" Type="{REL_NS}/styles" '
            'Target="styles.xml"/>'
        )
        overrides.append(
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        )

    parts["[Content_Types].xml"] = (
        f'<Types xmlns="{CONTENT_NS}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(overrides)}{content_types_extra}</Types>'
    ).encode("utf-8")
    parts["_rels/.rels"] = (
        f'<Relationships xmlns="{PACKAGE_REL_NS}">'
        f'<Relationship Id="rIdRoot" Type="{REL_NS}/officeDocument" '
        f'Target="xl/workbook.xml"/>{root_relationships_extra}</Relationships>'
    ).encode("utf-8")
    parts["xl/workbook.xml"] = (
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>'
        f'{"".join(workbook_sheet_nodes)}</sheets></workbook>'
    ).encode("utf-8")
    parts["xl/_rels/workbook.xml.rels"] = (
        f'<Relationships xmlns="{PACKAGE_REL_NS}">'
        f'{"".join(workbook_rel_nodes)}{workbook_relationships_extra}</Relationships>'
    ).encode("utf-8")
    return parts


def make_xlsx(
    *,
    sheets: list[tuple[str, str, str]] | None = None,
    shared_strings: str | None = None,
    styles: str | None = None,
    workbook_relationships_extra: str = "",
    root_relationships_extra: str = "",
    content_types_extra: str = "",
    extra_parts: dict[str, bytes] | None = None,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    parts = _base_parts(
        sheets=sheets,
        shared_strings=shared_strings,
        styles=styles,
        workbook_relationships_extra=workbook_relationships_extra,
        root_relationships_extra=root_relationships_extra,
        content_types_extra=content_types_extra,
    )
    parts.update(extra_parts or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def read_csv_text(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


class CsvInputTests(unittest.TestCase):
    def test_utf8_bom_csv_is_canonicalized(self) -> None:
        payload = (
            '\ufeff파일,화면 자막\r\nintro.mp4,"안녕\r세상"\r\n'
        ).encode("utf-8")
        text, canonical, description = subject.decode_uploaded_plan(
            "timeline.CSV", payload, kind="timeline", max_rows=5
        )

        self.assertEqual(description, "CSV 파일")
        self.assertTrue(canonical.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(canonical[3:].decode("utf-8"), text)
        self.assertEqual(
            read_csv_text(text),
            [["파일", "화면 자막"], ["intro.mp4", "안녕\n세상"]],
        )
        self.assertTrue(text.endswith("\n"))

    def test_csv_rejects_non_utf8_and_row_limit(self) -> None:
        with self.assertRaisesRegex(subject.PlanInputError, "CSV UTF-8"):
            subject.decode_uploaded_plan(
                "timeline.csv", "파일\n사진.jpg\n".encode("cp949"),
                kind="timeline", max_rows=5,
            )
        with self.assertRaisesRegex(subject.PlanInputError, "최대 1개"):
            subject.decode_uploaded_plan(
                "timeline.csv", b"file\na.mp4\nb.mp4\n",
                kind="timeline", max_rows=1,
            )

    def test_csv_size_and_excessive_blank_rows_are_rejected_early(self) -> None:
        with mock.patch.object(subject, "_MAX_CSV_BYTES", 10):
            with self.assertRaisesRegex(subject.PlanInputError, "10 MiB"):
                subject.decode_uploaded_plan(
                    "timeline.csv", b"file\n" + b"x" * 20,
                    kind="timeline", max_rows=1,
                )

        with self.assertRaisesRegex(subject.PlanInputError, "빈 행.*너무 많습니다"):
            subject.decode_uploaded_plan(
                "timeline.csv", b"file\n" + b"\n" * 1_100,
                kind="timeline", max_rows=1,
            )

    def test_numbers_and_other_formats_have_actionable_guidance(self) -> None:
        with self.assertRaisesRegex(
            subject.PlanInputError,
            "파일 → 다음으로 내보내기 → Excel",
        ) as context:
            subject.decode_uploaded_plan(
                "timeline.numbers", b"anything", kind="timeline", max_rows=5
            )
        self.assertEqual(str(context.exception), subject.NUMBERS_EXPORT_GUIDANCE)

        with self.assertRaisesRegex(subject.PlanInputError, "Excel 통합 문서"):
            subject.decode_uploaded_plan(
                "timeline.xls", b"anything", kind="timeline", max_rows=5
            )
        with self.assertRaisesRegex(subject.PlanInputError, "사진·영상"):
            subject.decode_uploaded_plan(
                "photo.png", b"anything", kind="timeline", max_rows=5
            )

    def test_invalid_options_are_rejected(self) -> None:
        with self.assertRaisesRegex(subject.PlanInputError, "kind"):
            subject.decode_uploaded_plan("a.csv", b"a\n", kind="clips", max_rows=1)
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(subject.PlanInputError, "max_rows"):
                    subject.decode_uploaded_plan(
                        "a.csv", b"a\n", kind="timeline", max_rows=value  # type: ignore[arg-type]
                    )

    def test_csv_header_must_really_be_first_row(self) -> None:
        with self.assertRaisesRegex(subject.PlanInputError, "머리글.*1행"):
            subject.decode_uploaded_plan(
                "timeline.csv", b"\nfile\na.mp4\n", kind="timeline", max_rows=5
            )

    def test_beginner_csv_and_excel_templates_keep_the_same_six_columns(self) -> None:
        templates = Path(__file__).resolve().parents[1] / "templates"
        expected = [
            "파일",
            "영상 원본 시작",
            "영상 원본 끝",
            "사진 표시 시간(초)",
            "화면 자막",
            "소리",
        ]

        csv_text, _, _ = subject.decode_uploaded_plan(
            "simple_timeline.csv",
            (templates / "simple_timeline.csv").read_bytes(),
            kind="timeline",
            max_rows=20,
        )
        xlsx_text, _, _ = subject.decode_uploaded_plan(
            "simple_timeline.xlsx",
            (templates / "simple_timeline.xlsx").read_bytes(),
            kind="timeline",
            max_rows=20,
        )

        self.assertEqual(read_csv_text(csv_text)[0], expected)
        self.assertEqual(read_csv_text(xlsx_text)[0], expected)


class XlsxValueTests(unittest.TestCase):
    def test_direction_specific_conform_headers_are_preserved(self) -> None:
        sheet = worksheet_xml(
            [
                (
                    1,
                    [
                        inline_cell("A1", "파일"),
                        inline_cell("B1", "세로 화면 맞춤"),
                        inline_cell("C1", "가로 화면 맞춤"),
                    ],
                ),
                (
                    2,
                    [
                        inline_cell("A2", "scene.png"),
                        inline_cell("B2", "화면 채우기"),
                        inline_cell("C2", "전체 보이기"),
                    ],
                ),
            ]
        )
        text, _, _ = subject.decode_uploaded_plan(
            "plan.xlsx",
            make_xlsx(sheets=[("timeline", "visible", sheet)]),
            kind="timeline",
            max_rows=10,
        )
        self.assertEqual(
            read_csv_text(text),
            [
                ["파일", "세로 화면 맞춤", "가로 화면 맞춤"],
                ["scene.png", "화면 채우기", "전체 보이기"],
            ],
        )

    def test_one_visible_sheet_uses_inline_strings_and_numbers(self) -> None:
        sheet = worksheet_xml(
            [
                (1, [inline_cell("A1", "파일"), inline_cell("B1", "메모")]),
                (
                    2,
                    [
                        inline_cell("A2", "cafe\r\n첫 장면.mov"),
                        number_cell("B2", "1.2300"),
                    ],
                ),
            ]
        )
        text, canonical, description = subject.decode_uploaded_plan(
            "plan.XLSX",
            make_xlsx(sheets=[("내 기획", "visible", sheet)]),
            kind="timeline",
            max_rows=10,
        )

        self.assertEqual(description, "Excel 파일 · 시트: 내 기획")
        self.assertEqual(
            read_csv_text(text),
            [["파일", "메모"], ["cafe\n첫 장면.mov", "1.23"]],
        )
        self.assertEqual(canonical, b"\xef\xbb\xbf" + text.encode("utf-8"))

    def test_shared_rich_strings_and_boolean_cells(self) -> None:
        shared = (
            f'<sst xmlns="{MAIN_NS}"><si><t>파</t><r><t>일</t></r></si>'
            '<si><t>clip.mov</t></si></sst>'
        )
        sheet = worksheet_xml(
            [
                (1, [typed_cell("A1", "s", "0"), inline_cell("B1", "소리")]),
                (2, [typed_cell("A2", "s", "1"), typed_cell("B2", "b", "1")]),
            ]
        )
        text, _, _ = subject.decode_uploaded_plan(
            "plan.xlsx",
            make_xlsx(
                sheets=[("Sheet1", "visible", sheet)],
                shared_strings=shared,
            ),
            kind="timeline",
            max_rows=2,
        )
        self.assertEqual(read_csv_text(text), [["파일", "소리"], ["clip.mov", "TRUE"]])

    def test_excel_time_and_duration_styles_become_time_text(self) -> None:
        styles = (
            f'<styleSheet xmlns="{MAIN_NS}"><numFmts count="1">'
            '<numFmt numFmtId="164" formatCode="[h]:mm:ss.000"/></numFmts>'
            '<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="164"/>'
            '<xf numFmtId="46"/></cellXfs></styleSheet>'
        )
        sheet = worksheet_xml(
            [
                (1, [inline_cell("A1", "시작"), inline_cell("B1", "끝")]),
                (
                    2,
                    [
                        number_cell("A2", "0.0000173611111111111", style=1),
                        number_cell("B2", "1.5", style=2),
                    ],
                ),
            ]
        )
        text, _, _ = subject.decode_uploaded_plan(
            "subtitles.xlsx",
            make_xlsx(sheets=[("자막", "visible", sheet)], styles=styles),
            kind="subtitles",
            max_rows=5,
        )
        self.assertEqual(
            read_csv_text(text),
            [["시작", "끝"], ["00:00:01.500", "36:00:00.000"]],
        )

    def test_elapsed_minutes_are_time_and_negative_time_is_rejected(self) -> None:
        styles = (
            f'<styleSheet xmlns="{MAIN_NS}"><numFmts count="1">'
            '<numFmt numFmtId="164" formatCode="[m]"/></numFmts>'
            '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164"/>'
            '</cellXfs></styleSheet>'
        )
        positive = worksheet_xml(
            [(1, [inline_cell("A1", "시작")]), (2, [number_cell("A2", "0.5", style=1)])]
        )
        text, _, _ = subject.decode_uploaded_plan(
            "subtitles.xlsx",
            make_xlsx(sheets=[("자막", "visible", positive)], styles=styles),
            kind="subtitles",
            max_rows=5,
        )
        self.assertEqual(read_csv_text(text), [["시작"], ["12:00:00.000"]])

        negative = worksheet_xml(
            [(1, [inline_cell("A1", "시작")]), (2, [number_cell("A2", "-0.01", style=1)])]
        )
        with self.assertRaisesRegex(subject.PlanInputError, "음수 시간.*A2"):
            subject.decode_uploaded_plan(
                "subtitles.xlsx",
                make_xlsx(sheets=[("자막", "visible", negative)], styles=styles),
                kind="subtitles",
                max_rows=5,
            )

    def test_date_formula_error_and_merge_cells_are_rejected(self) -> None:
        styles = (
            f'<styleSheet xmlns="{MAIN_NS}"><cellXfs count="2">'
            '<xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>'
        )
        cases = {
            "날짜 형식": (
                worksheet_xml(
                    [(1, [inline_cell("A1", "시작")]), (2, [number_cell("A2", "45000", style=1)])]
                ),
                styles,
            ),
            "수식을 사용할 수 없습니다": (
                worksheet_xml(
                    [
                        (1, [inline_cell("A1", "파일")]),
                        (2, ['<c r="A2"><f>1+1</f><v>2</v></c>']),
                    ]
                ),
                None,
            ),
            "오류 값": (
                worksheet_xml(
                    [(1, [inline_cell("A1", "파일")]), (2, [typed_cell("A2", "e", "#N/A")])]
                ),
                None,
            ),
            "병합 셀": (
                worksheet_xml(
                    [(1, [inline_cell("A1", "파일")])],
                    tail='<mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells>',
                ),
                None,
            ),
        }
        for message, (sheet, case_styles) in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(subject.PlanInputError, message):
                    subject.decode_uploaded_plan(
                        "plan.xlsx",
                        make_xlsx(
                            sheets=[("Sheet1", "visible", sheet)],
                            styles=case_styles,
                        ),
                        kind="timeline",
                        max_rows=5,
                    )

    def test_header_must_be_in_row_one(self) -> None:
        sheet = worksheet_xml(
            [(2, [inline_cell("A2", "파일")]), (3, [inline_cell("A3", "clip.mp4")])]
        )
        with self.assertRaisesRegex(subject.PlanInputError, "1행.*머리글"):
            subject.decode_uploaded_plan(
                "plan.xlsx", make_xlsx(sheets=[("Sheet1", "visible", sheet)]),
                kind="timeline", max_rows=5,
            )

    def test_row_column_and_cell_size_limits(self) -> None:
        too_many_rows = worksheet_xml(
            [
                (1, [inline_cell("A1", "파일")]),
                (2, [inline_cell("A2", "a.mov")]),
                (3, [inline_cell("A3", "b.mov")]),
            ]
        )
        with self.assertRaisesRegex(subject.PlanInputError, "최대 1개"):
            subject.decode_uploaded_plan(
                "plan.xlsx", make_xlsx(sheets=[("Sheet1", "visible", too_many_rows)]),
                kind="timeline", max_rows=1,
            )

        too_many_columns = worksheet_xml(
            [(1, [inline_cell("A1", "파일"), inline_cell("AG1", "메모")])]
        )
        with self.assertRaisesRegex(subject.PlanInputError, "최대 32열"):
            subject.decode_uploaded_plan(
                "plan.xlsx", make_xlsx(sheets=[("Sheet1", "visible", too_many_columns)]),
                kind="timeline", max_rows=1,
            )

        huge_cell = worksheet_xml([(1, [inline_cell("A1", "가" * 10_001)])])
        with self.assertRaisesRegex(subject.PlanInputError, "10,000자"):
            subject.decode_uploaded_plan(
                "plan.xlsx", make_xlsx(sheets=[("Sheet1", "visible", huge_cell)]),
                kind="timeline", max_rows=1,
            )

        huge_reference = "Z" * 100_000 + "1"
        invalid_reference = worksheet_xml(
            [(1, [inline_cell(huge_reference, "파일")])]
        )
        with self.assertRaisesRegex(subject.PlanInputError, "셀 주소") as context:
            subject.decode_uploaded_plan(
                "plan.xlsx",
                make_xlsx(
                    sheets=[("Sheet1", "visible", invalid_reference)],
                    compression=zipfile.ZIP_STORED,
                ),
                kind="timeline",
                max_rows=1,
            )
        self.assertLess(len(str(context.exception)), 300)

    def test_nonempty_cell_and_total_character_limits(self) -> None:
        sheet = worksheet_xml(
            [
                (1, [inline_cell("A1", "파일"), inline_cell("B1", "메모")]),
                (2, [inline_cell("A2", "a.mov"), inline_cell("B2", "abcd")]),
            ]
        )
        payload = make_xlsx(sheets=[("Sheet1", "visible", sheet)])
        with mock.patch.object(subject, "_MAX_NONEMPTY_CELLS", 3):
            with self.assertRaisesRegex(subject.PlanInputError, "50,000개"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", payload, kind="timeline", max_rows=5
                )
        with mock.patch.object(subject, "_MAX_TOTAL_CHARACTERS", 10):
            with self.assertRaisesRegex(subject.PlanInputError, "5,000,000자"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", payload, kind="timeline", max_rows=5
                )
        with mock.patch.object(subject, "_MAX_WORKSHEET_CELLS", 3):
            with self.assertRaisesRegex(subject.PlanInputError, "빈 셀을 포함"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", payload, kind="timeline", max_rows=5
                )

    def test_extreme_decimal_exponents_are_rejected_before_expansion(self) -> None:
        for value in ("1E+309", "1E-325", "1E+999999999"):
            with self.subTest(value=value):
                sheet = worksheet_xml(
                    [(1, [inline_cell("A1", "시간")]), (2, [number_cell("A2", value)])]
                )
                with self.assertRaisesRegex(subject.PlanInputError, "숫자 범위"):
                    subject.decode_uploaded_plan(
                        "plan.xlsx",
                        make_xlsx(sheets=[("Sheet1", "visible", sheet)]),
                        kind="timeline",
                        max_rows=5,
                    )

    def test_existing_excel_template_is_readable_when_present(self) -> None:
        template = Path(__file__).resolve().parents[1] / "templates" / "simple_timeline.xlsx"
        if not template.exists():
            self.skipTest("저장소에 선택적 simple_timeline.xlsx 템플릿이 없음")
        text, canonical, description = subject.decode_uploaded_plan(
            template.name,
            template.read_bytes(),
            kind="timeline",
            max_rows=10_000,
        )
        self.assertEqual(read_csv_text(text)[0][0], "파일")
        self.assertTrue(canonical.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Excel 파일", description)


class XlsxSheetSelectionTests(unittest.TestCase):
    @staticmethod
    def _sheet(label: str = "파일") -> str:
        return worksheet_xml([(1, [inline_cell("A1", label)])])

    def test_kind_selects_named_sheet_among_multiple_visible_sheets(self) -> None:
        payload = make_xlsx(
            sheets=[
                ("설명", "visible", self._sheet("안내")),
                ("타임라인", "visible", self._sheet("파일")),
                ("자막", "visible", self._sheet("번호")),
            ]
        )
        timeline, _, timeline_source = subject.decode_uploaded_plan(
            "plan.xlsx", payload, kind="timeline", max_rows=5
        )
        subtitles, _, subtitle_source = subject.decode_uploaded_plan(
            "plan.xlsx", payload, kind="subtitles", max_rows=5
        )
        self.assertEqual(read_csv_text(timeline), [["파일"]])
        self.assertIn("타임라인", timeline_source)
        self.assertEqual(read_csv_text(subtitles), [["번호"]])
        self.assertIn("자막", subtitle_source)

    def test_ambiguous_or_missing_preferred_sheet_lists_visible_names(self) -> None:
        ambiguous = make_xlsx(
            sheets=[
                ("timeline", "visible", self._sheet()),
                ("타임라인", "visible", self._sheet()),
            ]
        )
        with self.assertRaisesRegex(subject.PlanInputError, "timeline.*타임라인"):
            subject.decode_uploaded_plan(
                "plan.xlsx", ambiguous, kind="timeline", max_rows=5
            )

        missing = make_xlsx(
            sheets=[
                ("영상", "visible", self._sheet()),
                ("설명", "visible", self._sheet()),
            ]
        )
        with self.assertRaisesRegex(subject.PlanInputError, "영상, 설명"):
            subject.decode_uploaded_plan(
                "plan.xlsx", missing, kind="timeline", max_rows=5
            )

    def test_hidden_sheets_are_not_selected_and_sheet_count_is_limited(self) -> None:
        hidden = make_xlsx(
            sheets=[
                ("timeline", "hidden", self._sheet()),
                ("타임라인", "veryHidden", self._sheet()),
            ]
        )
        with self.assertRaisesRegex(subject.PlanInputError, "보이는 Excel 시트가 없습니다"):
            subject.decode_uploaded_plan(
                "plan.xlsx", hidden, kind="timeline", max_rows=5
            )

        too_many = [
            (f"Sheet{index}", "hidden", self._sheet()) for index in range(1, 22)
        ]
        with self.assertRaisesRegex(subject.PlanInputError, "최대 20개"):
            subject.decode_uploaded_plan(
                "plan.xlsx", make_xlsx(sheets=too_many),
                kind="timeline", max_rows=5,
            )


class XlsxSecurityTests(unittest.TestCase):
    def test_standard_core_properties_relationship_is_allowed(self) -> None:
        core_relationship = (
            '<Relationship Id="rIdCore" '
            'Type="http://schemas.openxmlformats.org/package/2006/'
            'relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/>'
        )
        payload = make_xlsx(
            root_relationships_extra=core_relationship,
            extra_parts={"docProps/core.xml": b"<coreProperties/>"},
        )
        text, _, description = subject.decode_uploaded_plan(
            "excel.xlsx", payload, kind="timeline", max_rows=5
        )
        self.assertEqual(read_csv_text(text)[0][0], "파일")
        self.assertIn("Excel 파일", description)

    def test_required_parts_and_valid_zip_are_required(self) -> None:
        with self.assertRaisesRegex(subject.PlanInputError, "올바른 .xlsx"):
            subject.decode_uploaded_plan(
                "plan.xlsx", b"not a zip", kind="timeline", max_rows=5
            )

        parts = _base_parts()
        del parts["xl/workbook.xml"]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content)
        with self.assertRaisesRegex(subject.PlanInputError, "필수 구성요소"):
            subject.decode_uploaded_plan(
                "plan.xlsx", buffer.getvalue(), kind="timeline", max_rows=5
            )

    def test_size_entry_and_compression_ratio_limits(self) -> None:
        valid = make_xlsx()
        with mock.patch.object(subject, "_MAX_COMPRESSED_BYTES", 10):
            with self.assertRaisesRegex(subject.PlanInputError, "10 MiB"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", valid, kind="timeline", max_rows=5
                )

        with mock.patch.object(subject, "_MAX_ZIP_ENTRIES", 4):
            with self.assertRaisesRegex(subject.PlanInputError, "최대 256개"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", valid, kind="timeline", max_rows=5
                )

        member_payload = make_xlsx(extra_parts={"docProps/large.bin": b"123456"})
        with mock.patch.object(subject, "_MAX_MEMBER_BYTES", 5):
            with self.assertRaisesRegex(subject.PlanInputError, "32 MiB"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", member_payload, kind="timeline", max_rows=5
                )
        with mock.patch.object(subject, "_MAX_UNCOMPRESSED_BYTES", 100):
            with self.assertRaisesRegex(subject.PlanInputError, "64 MiB"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", valid, kind="timeline", max_rows=5
                )

        ratio_payload = make_xlsx(extra_parts={"docProps/repeated.bin": b"0" * 100_000})
        with self.assertRaisesRegex(subject.PlanInputError, "압축률"):
            subject.decode_uploaded_plan(
                "plan.xlsx", ratio_payload, kind="timeline", max_rows=5
            )

    def test_duplicate_unsafe_encrypted_symlink_and_compression_are_rejected(self) -> None:
        duplicate = io.BytesIO(make_xlsx())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(duplicate, "a", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("xl/workbook.xml", b"duplicate")
        with self.assertRaisesRegex(subject.PlanInputError, "중복된 내부 항목"):
            subject.decode_uploaded_plan(
                "plan.xlsx", duplicate.getvalue(), kind="timeline", max_rows=5
            )

        unsafe = make_xlsx(extra_parts={"../evil.xml": b"<x/>"})
        with self.assertRaisesRegex(subject.PlanInputError, "내부 경로"):
            subject.decode_uploaded_plan(
                "plan.xlsx", unsafe, kind="timeline", max_rows=5
            )

        symlink_parts = _base_parts()
        symlink_buffer = io.BytesIO()
        with zipfile.ZipFile(symlink_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in symlink_parts.items():
                archive.writestr(name, content)
            info = zipfile.ZipInfo("docProps/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"target")
        with self.assertRaisesRegex(subject.PlanInputError, "심볼릭 링크"):
            subject.decode_uploaded_plan(
                "plan.xlsx", symlink_buffer.getvalue(), kind="timeline", max_rows=5
            )

        bzip = make_xlsx(compression=zipfile.ZIP_BZIP2)
        with self.assertRaisesRegex(subject.PlanInputError, "Deflate"):
            subject.decode_uploaded_plan(
                "plan.xlsx", bzip, kind="timeline", max_rows=5
            )

        encrypted = bytearray(make_xlsx())
        local = encrypted.find(b"PK\x03\x04")
        central = encrypted.find(b"PK\x01\x02")
        self.assertGreaterEqual(local, 0)
        self.assertGreaterEqual(central, 0)
        encrypted[local + 6 : local + 8] = (
            int.from_bytes(encrypted[local + 6 : local + 8], "little") | 1
        ).to_bytes(2, "little")
        encrypted[central + 8 : central + 10] = (
            int.from_bytes(encrypted[central + 8 : central + 10], "little") | 1
        ).to_bytes(2, "little")
        with self.assertRaisesRegex(subject.PlanInputError, "암호화"):
            subject.decode_uploaded_plan(
                "plan.xlsx", bytes(encrypted), kind="timeline", max_rows=5
            )

    def test_crc_failure_is_rejected_before_parsing(self) -> None:
        with mock.patch.object(zipfile.ZipFile, "testzip", return_value="xl/workbook.xml"):
            with self.assertRaisesRegex(subject.PlanInputError, "CRC"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", make_xlsx(), kind="timeline", max_rows=5
                )
        with mock.patch.object(
            zipfile.ZipFile, "testzip", side_effect=zlib.error("bad deflate")
        ):
            with self.assertRaisesRegex(subject.PlanInputError, "CRC"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", make_xlsx(), kind="timeline", max_rows=5
                )

    def test_macro_activex_embeddings_and_custom_ui_are_rejected(self) -> None:
        dangerous_names = (
            "xl/vbaProject.bin",
            "xl/activeX/activeX1.bin",
            "xl/embeddings/oleObject1.bin",
            "customUI/customUI.xml",
        )
        for name in dangerous_names:
            with self.subTest(name=name):
                with self.assertRaisesRegex(subject.PlanInputError, "매크로.*ActiveX"):
                    subject.decode_uploaded_plan(
                        "plan.xlsx",
                        make_xlsx(extra_parts={name: b"content"}),
                        kind="timeline",
                        max_rows=5,
                    )

        content_type = (
            '<Override PartName="/xl/vbaProject.bin" '
            'ContentType="application/vnd.ms-office.vbaProject"/>'
        )
        with self.assertRaisesRegex(subject.PlanInputError, "매크로.*ActiveX"):
            subject.decode_uploaded_plan(
                "plan.xlsx", make_xlsx(content_types_extra=content_type),
                kind="timeline", max_rows=5,
            )

        active_x_relationship = (
            f'<Relationship Id="rIdControl" Type="{REL_NS}/control" '
            'Target="controls/control1.bin"/>'
        )
        with self.assertRaisesRegex(subject.PlanInputError, "ActiveX.*내장 개체"):
            subject.decode_uploaded_plan(
                "plan.xlsx",
                make_xlsx(workbook_relationships_extra=active_x_relationship),
                kind="timeline",
                max_rows=5,
            )

        xlm_relationship = (
            f'<Relationship Id="rIdXlm" Type="{REL_NS}/xlMacrosheet" '
            'Target="worksheets/legacy.xml"/>'
        )
        with self.assertRaisesRegex(subject.PlanInputError, "매크로.*ActiveX"):
            subject.decode_uploaded_plan(
                "plan.xlsx",
                make_xlsx(workbook_relationships_extra=xlm_relationship),
                kind="timeline",
                max_rows=5,
            )

        xlm_content_type = (
            '<Override PartName="/xl/worksheets/legacy.xml" '
            'ContentType="application/vnd.ms-excel.macrosheet+xml"/>'
        )
        with self.assertRaisesRegex(subject.PlanInputError, "매크로.*ActiveX"):
            subject.decode_uploaded_plan(
                "plan.xlsx", make_xlsx(content_types_extra=xlm_content_type),
                kind="timeline", max_rows=5,
            )

    def test_xml_relationship_and_object_count_limits(self) -> None:
        valid = make_xlsx()
        with mock.patch.object(subject, "_MAX_RELATIONSHIP_PART_BYTES", 10):
            with self.assertRaisesRegex(subject.PlanInputError, "관계 정보가 너무 큽니다"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", valid, kind="timeline", max_rows=5
                )

        with mock.patch.object(subject, "_MAX_RELATIONSHIPS", 1):
            with self.assertRaisesRegex(subject.PlanInputError, "최대 2,048개"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", valid, kind="timeline", max_rows=5
                )

        with mock.patch.object(subject, "_MAX_XML_ELEMENTS", 2):
            with self.assertRaisesRegex(subject.PlanInputError, "XML 요소"):
                subject.decode_uploaded_plan(
                    "plan.xlsx", valid, kind="timeline", max_rows=5
                )

    def test_doctype_entity_and_external_relationships_are_rejected(self) -> None:
        doctype = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
        with self.assertRaisesRegex(subject.PlanInputError, "엔터티"):
            subject.decode_uploaded_plan(
                "plan.xlsx", make_xlsx(extra_parts={"docProps/core.xml": doctype}),
                kind="timeline", max_rows=5,
            )

        external = (
            f'<Relationship Id="rIdExternal" Type="{REL_NS}/hyperlink" '
            'Target="https://example.com" TargetMode="External"/>'
        )
        with self.assertRaisesRegex(subject.PlanInputError, "외부 파일"):
            subject.decode_uploaded_plan(
                "plan.xlsx",
                make_xlsx(workbook_relationships_extra=external),
                kind="timeline",
                max_rows=5,
            )

    def test_relationship_path_traversal_is_rejected(self) -> None:
        parts = _base_parts()
        parts["xl/_rels/workbook.xml.rels"] = (
            f'<Relationships xmlns="{PACKAGE_REL_NS}">'
            f'<Relationship Id="rId1" Type="{REL_NS}/worksheet" '
            'Target="../../outside.xml"/></Relationships>'
        ).encode("utf-8")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content)
        with self.assertRaisesRegex(subject.PlanInputError, "관계 대상"):
            subject.decode_uploaded_plan(
                "plan.xlsx", buffer.getvalue(), kind="timeline", max_rows=5
            )


if __name__ == "__main__":
    unittest.main()
