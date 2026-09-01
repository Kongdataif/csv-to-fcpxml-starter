#!/usr/bin/env python3
"""업로드된 CSV/Excel 기획표를 안전한 UTF-8 CSV로 정규화한다.

Colab 사용자는 같은 표를 CSV 또는 ``.xlsx``로 올릴 수 있다. 이 모듈은
Excel을 실행하지 않고, Python 표준 라이브러리로 OOXML의 셀 값만 읽는다.
수식·매크로·외부 연결과 비정상 ZIP은 입력 단계에서 거부한다.

공개 진입점은 :func:`decode_uploaded_plan` 하나다. 반환값은 다음과 같다.

``csv_text``
    BOM이 없는 정규 CSV 문자열. ``csv.DictReader``에 바로 전달할 수 있다.
``canonical_bytes``
    Excel에서도 한글이 잘 보이는 UTF-8 BOM 포함 CSV 바이트.
``source_description``
    업로드 결과 화면에 표시할 짧은 원본 설명.
"""

from __future__ import annotations

import csv
import io
import posixpath
import re
import stat
import unicodedata
import zipfile
import zlib
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


class PlanInputError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 기획표 입력 오류."""


# 설명적인 이전 이름도 호환용으로 둔다.
SpreadsheetInputError = PlanInputError


NUMBERS_EXPORT_GUIDANCE = (
    "Numbers 파일(.numbers)은 그대로 업로드할 수 없습니다. "
    "Numbers에서 파일을 연 뒤 '파일 → 다음으로 내보내기 → Excel'을 선택해 "
    ".xlsx로 저장하고, 저장한 .xlsx 파일을 다시 업로드해주세요."
)

SUPPORTED_EXTENSIONS = (".csv", ".xlsx")

_MAX_CSV_BYTES = 10 * 1024 * 1024
_MAX_COMPRESSED_BYTES = 10 * 1024 * 1024
_MAX_ZIP_ENTRIES = 256
_MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
_MAX_SHEETS = 20
_MAX_COLUMNS = 32
_MAX_NONEMPTY_CELLS = 50_000
_MAX_WORKSHEET_CELLS = 100_000
_MAX_TOTAL_CHARACTERS = 5_000_000
_MAX_CELL_CHARACTERS = 10_000
_MAX_XML_PART_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_XML_BYTES = 32 * 1024 * 1024
_MAX_RELATIONSHIP_PART_BYTES = 1 * 1024 * 1024
_MAX_RELATIONSHIPS = 2_048
_MAX_XML_ELEMENTS = 200_000
_MAX_SHARED_STRINGS = 100_000
_MAX_CELL_STYLES = 4_096

_REQUIRED_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
}

_DANGEROUS_PATH_MARKERS = (
    "vbaproject",
    "/activex/",
    "/embeddings/",
    "customui/",
    "/macrosheets/",
    "/dialogsheets/",
)

_DANGEROUS_CONTENT_TYPE_MARKERS = (
    "macroenabled",
    "vba",
    "activex",
    "oleobject",
    "customui",
    "macrosheet",
    "dialogsheet",
    "externallink",
    "querytable",
    "connections",
)

_DANGEROUS_RELATIONSHIP_TYPE_NAMES = {
    "vbaproject",
    "activex",
    "activexcontrol",
    "activexcontrolbinary",
    "customui",
    "control",
    "ctrlprop",
    "oleobject",
    "package",
    "externallink",
    "externallinkpath",
    "xlmacrosheet",
    "xlintlmacrosheet",
    "dialogsheet",
    "querytable",
    "connections",
}

_RELATIONSHIP_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_STRICT_RELATIONSHIP_NS = "http://purl.oclc.org/ooxml/officeDocument/relationships"
_CELL_REF_RE = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]{0,6})$")
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")
_MAX_EXCEL_COLUMN = 16_384  # XFD
_MAX_EXCEL_ROW = 1_048_576

# Excel 기본 표시 형식 ID. 날짜가 포함된 셀은 타임라인 시각으로 오인하지
# 않도록 거부하고, 시간 전용 형식만 초 단위 문자열로 바꾼다.
_BUILTIN_DATE_FORMAT_IDS = {
    14,
    15,
    16,
    17,
    22,
    *range(27, 37),
    *range(50, 59),
}
_BUILTIN_TIME_FORMAT_IDS = {18, 19, 20, 21, 45, 46, 47}


def decode_uploaded_plan(
    name: str,
    payload: bytes | bytearray | memoryview,
    *,
    kind: str,
    max_rows: int,
) -> tuple[str, bytes, str]:
    """CSV 또는 XLSX 기획표를 표준 CSV로 바꾼다.

    ``kind``는 ``"timeline"`` 또는 ``"subtitles"``다. 여러 시트가 보이는
    Excel 파일에서는 이 값에 따라 ``timeline``/``타임라인`` 또는
    ``subtitles``/``자막`` 시트를 고른다. 한 시트만 보이면 그 시트를 쓴다.
    ``max_rows``는 머리글을 제외한 실제 데이터 행 제한이다.
    """

    normalized_kind = str(kind).strip().lower()
    if normalized_kind not in {"timeline", "subtitles"}:
        raise SpreadsheetInputError(
            "kind는 'timeline' 또는 'subtitles'여야 합니다."
        )
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise SpreadsheetInputError("max_rows는 1 이상의 정수여야 합니다.")
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise SpreadsheetInputError("업로드 파일 내용을 바이트 형식으로 전달해주세요.")

    filename = str(name or "").strip()
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    raw = bytes(payload)

    if suffix == ".numbers":
        raise SpreadsheetInputError(NUMBERS_EXPORT_GUIDANCE)
    if suffix == ".csv":
        if len(raw) > _MAX_CSV_BYTES:
            raise SpreadsheetInputError(
                "CSV 파일이 너무 큽니다. CSV 크기는 10 MiB 이하여야 합니다."
            )
        rows = _decode_csv(raw, max_rows=max_rows)
        csv_text, canonical_bytes = _canonical_csv(rows)
        return csv_text, canonical_bytes, "CSV 파일"
    if suffix == ".xlsx":
        rows, sheet_name = _decode_xlsx(
            raw,
            kind=normalized_kind,
            max_rows=max_rows,
        )
        csv_text, canonical_bytes = _canonical_csv(rows)
        return csv_text, canonical_bytes, f"Excel 파일 · 시트: {sheet_name}"

    if suffix in {".xls", ".xlsm", ".xlsb", ".ods", ".tsv"}:
        shown = suffix or "(확장자 없음)"
        raise SpreadsheetInputError(
            f"지원하지 않는 표 파일 형식입니다: {shown}. "
            "Excel 또는 Numbers에서 'Excel 통합 문서(.xlsx)' 또는 "
            "'CSV UTF-8(.csv)'로 저장한 뒤 다시 업로드해주세요."
        )
    raise SpreadsheetInputError(
        "기획표는 .csv 또는 .xlsx 파일로 업로드해주세요. "
        "사진·영상 파일은 다음 미디어 업로드 단계에서 선택합니다."
    )


def _decode_csv(payload: bytes, *, max_rows: int) -> list[list[str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SpreadsheetInputError(
            "CSV의 한글 인코딩을 읽을 수 없습니다. Excel 또는 Numbers에서 "
            "'CSV UTF-8(.csv)'로 다시 저장해주세요."
        ) from exc

    try:
        rows = _normalize_table(
            (list(row) for row in csv.reader(io.StringIO(text, newline=""), strict=True)),
            max_rows=max_rows,
            source="CSV",
        )
    except csv.Error as exc:
        raise SpreadsheetInputError(
            f"CSV 표 구조를 읽을 수 없습니다: {exc}. 따옴표와 쉼표를 확인해주세요."
        ) from exc
    return rows


def _decode_xlsx(
    payload: bytes,
    *,
    kind: str,
    max_rows: int,
) -> tuple[list[list[str]], str]:
    if len(payload) > _MAX_COMPRESSED_BYTES:
        raise SpreadsheetInputError(
            "Excel 파일이 너무 큽니다. 압축된 .xlsx 크기는 10 MiB 이하여야 합니다."
        )
    if not payload:
        raise SpreadsheetInputError("비어 있는 Excel 파일은 읽을 수 없습니다.")

    try:
        workbook_zip = zipfile.ZipFile(io.BytesIO(payload), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise SpreadsheetInputError(
            "올바른 .xlsx 파일이 아닙니다. Excel 통합 문서로 다시 저장해주세요."
        ) from exc

    with workbook_zip as archive:
        parts = _preflight_zip(archive)
        xml_parts = _read_and_check_xml_parts(archive, parts)
        relationships = _parse_all_relationships(xml_parts)
        _validate_content_types(xml_parts["[Content_Types].xml"])
        _validate_root_workbook_relationship(relationships)

        workbook_root = _parse_xml_part(
            xml_parts["xl/workbook.xml"], "xl/workbook.xml"
        )
        sheets = _read_workbook_sheets(workbook_root)
        selected = _select_visible_sheet(sheets, kind=kind)

        workbook_rels_name = "xl/_rels/workbook.xml.rels"
        workbook_rels = relationships.get(workbook_rels_name)
        if workbook_rels is None:
            raise SpreadsheetInputError(
                "Excel 파일에 통합문서 관계 정보가 없습니다. 파일을 다시 저장해주세요."
            )

        sheet_relation = workbook_rels.get(selected.relationship_id)
        if sheet_relation is None or not sheet_relation.rel_type.lower().endswith(
            "/worksheet"
        ):
            raise SpreadsheetInputError(
                f"'{selected.name}' 시트의 데이터 위치를 찾을 수 없습니다."
            )
        sheet_part = sheet_relation.target_part
        if sheet_part not in xml_parts:
            raise SpreadsheetInputError(
                f"'{selected.name}' 시트 데이터가 Excel 파일 안에 없습니다."
            )

        shared_strings: list[str] = []
        shared_relation = _relationship_by_type(workbook_rels, "sharedstrings")
        if shared_relation is not None:
            if shared_relation.target_part not in xml_parts:
                raise SpreadsheetInputError("Excel 공유 문자열 표가 손상되었습니다.")
            shared_strings = _read_shared_strings(
                _parse_xml_part(
                    xml_parts[shared_relation.target_part],
                    shared_relation.target_part,
                )
            )

        style_classes: list[str] = ["general"]
        styles_relation = _relationship_by_type(workbook_rels, "styles")
        if styles_relation is not None:
            if styles_relation.target_part not in xml_parts:
                raise SpreadsheetInputError("Excel 셀 스타일 정보가 손상되었습니다.")
            style_classes = _read_style_classes(
                _parse_xml_part(
                    xml_parts[styles_relation.target_part],
                    styles_relation.target_part,
                )
            )

        worksheet_root = _parse_xml_part(xml_parts[sheet_part], sheet_part)
        rows = _read_worksheet(
            worksheet_root,
            shared_strings=shared_strings,
            style_classes=style_classes,
            max_rows=max_rows,
            sheet_name=selected.name,
        )
        return rows, selected.name


def _preflight_zip(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise SpreadsheetInputError(
            "Excel 파일 내부 항목이 너무 많습니다(최대 256개)."
        )

    parts: dict[str, zipfile.ZipInfo] = {}
    folded_names: set[str] = set()
    total_size = 0

    for info in infos:
        name = info.filename
        _validate_zip_member_name(name)
        folded = name.casefold()
        if name in parts or folded in folded_names:
            raise SpreadsheetInputError(
                f"Excel 파일에 중복된 내부 항목이 있습니다: {name}"
            )
        parts[name] = info
        folded_names.add(folded)

        if info.flag_bits & 0x1:
            raise SpreadsheetInputError(
                f"암호화된 Excel 내부 항목은 읽을 수 없습니다: {name}"
            )
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise SpreadsheetInputError(
                "Excel 파일은 저장 또는 Deflate 압축 방식만 사용할 수 있습니다."
            )
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if info.create_system == 3 and stat.S_ISLNK(unix_mode):
            raise SpreadsheetInputError(
                f"바로가기(심볼릭 링크)가 든 Excel 파일은 읽을 수 없습니다: {name}"
            )
        if info.file_size > _MAX_MEMBER_BYTES:
            raise SpreadsheetInputError(
                f"Excel 내부 항목이 너무 큽니다(최대 32 MiB): {name}"
            )
        total_size += info.file_size
        if total_size > _MAX_UNCOMPRESSED_BYTES:
            raise SpreadsheetInputError(
                "Excel 압축 해제 크기가 너무 큽니다(최대 64 MiB)."
            )
        if info.file_size:
            if info.compress_size == 0 or (
                info.file_size > info.compress_size * _MAX_COMPRESSION_RATIO
            ):
                raise SpreadsheetInputError(
                    f"비정상적으로 높은 압축률의 Excel 항목을 거부했습니다: {name}"
                )

        lowered = f"/{name.casefold().lstrip('/')}"
        if any(marker in lowered for marker in _DANGEROUS_PATH_MARKERS):
            raise SpreadsheetInputError(
                "매크로·ActiveX·내장 개체가 포함된 Excel 파일은 읽을 수 없습니다."
            )

    missing = sorted(_REQUIRED_PARTS - set(parts))
    if missing:
        raise SpreadsheetInputError(
            "Excel 필수 구성요소가 없습니다: " + ", ".join(missing)
        )

    try:
        bad_member = archive.testzip()
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError, zlib.error) as exc:
        raise SpreadsheetInputError(
            "Excel 압축 데이터의 CRC 검사가 실패했습니다. 파일을 다시 저장해주세요."
        ) from exc
    if bad_member is not None:
        raise SpreadsheetInputError(
            f"Excel 압축 데이터의 CRC 검사가 실패했습니다: {bad_member}"
        )
    return parts


def _validate_zip_member_name(name: str) -> None:
    if not name or "\x00" in name or "\\" in name:
        raise SpreadsheetInputError("Excel 내부 경로가 안전하지 않습니다.")
    if name.startswith("/") or _DRIVE_PATH_RE.match(name):
        raise SpreadsheetInputError(f"Excel 내부 절대 경로를 거부했습니다: {name}")
    components = name.split("/")
    if components[-1] == "":
        components = components[:-1]
    if not components or any(part in {"", ".", ".."} for part in components):
        raise SpreadsheetInputError(f"Excel 내부 경로를 거부했습니다: {name}")


def _read_and_check_xml_parts(
    archive: zipfile.ZipFile,
    parts: dict[str, zipfile.ZipInfo],
) -> dict[str, bytes]:
    xml_parts: dict[str, bytes] = {}
    total_xml_bytes = 0
    for name, info in parts.items():
        lowered = name.casefold()
        if not (lowered.endswith(".xml") or lowered.endswith(".rels")):
            continue
        if info.file_size > _MAX_XML_PART_BYTES:
            raise SpreadsheetInputError(
                f"Excel XML 구성요소가 너무 큽니다(최대 16 MiB): {name}"
            )
        if lowered.endswith(".rels") and info.file_size > _MAX_RELATIONSHIP_PART_BYTES:
            raise SpreadsheetInputError(
                f"Excel 관계 정보가 너무 큽니다(최대 1 MiB): {name}"
            )
        total_xml_bytes += info.file_size
        if total_xml_bytes > _MAX_TOTAL_XML_BYTES:
            raise SpreadsheetInputError(
                "Excel XML 전체 크기가 너무 큽니다(최대 32 MiB)."
            )
        try:
            raw = archive.read(info)
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError, zlib.error) as exc:
            raise SpreadsheetInputError(
                f"Excel 내부 XML을 읽을 수 없습니다: {name}"
            ) from exc
        # UTF-16 XML에서도 선언을 잡을 수 있도록 NUL을 없앤 바이트를 함께 본다.
        declaration_scan = raw.upper().replace(b"\x00", b"")
        if b"<!DOCTYPE" in declaration_scan or b"<!ENTITY" in declaration_scan:
            raise SpreadsheetInputError(
                f"외부 엔터티 선언이 든 Excel XML을 거부했습니다: {name}"
            )
        xml_parts[name] = raw
    return xml_parts


def _parse_xml_part(raw: bytes, name: str) -> ET.Element:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SpreadsheetInputError(
            f"Excel 내부 XML이 손상되었습니다: {name}"
        ) from exc
    if sum(1 for _ in root.iter()) > _MAX_XML_ELEMENTS:
        raise SpreadsheetInputError(
            f"Excel XML 요소가 너무 많습니다(최대 200,000개): {name}"
        )
    return root


class _Relationship:
    __slots__ = ("rel_id", "rel_type", "target_part")

    def __init__(self, rel_id: str, rel_type: str, target_part: str) -> None:
        self.rel_id = rel_id
        self.rel_type = rel_type
        self.target_part = target_part


def _parse_all_relationships(
    xml_parts: dict[str, bytes],
) -> dict[str, dict[str, _Relationship]]:
    result: dict[str, dict[str, _Relationship]] = {}
    total_relationships = 0
    for name, raw in xml_parts.items():
        if not name.casefold().endswith(".rels"):
            continue
        root = _parse_xml_part(raw, name)
        if _local_name(root.tag) != "Relationships":
            raise SpreadsheetInputError(
                f"Excel 관계 XML의 루트 요소가 올바르지 않습니다: {name}"
            )
        source_part = _source_part_for_relationships(name)
        entries: dict[str, _Relationship] = {}
        for node in root.iter():
            if _local_name(node.tag) != "Relationship":
                continue
            total_relationships += 1
            if total_relationships > _MAX_RELATIONSHIPS:
                raise SpreadsheetInputError(
                    "Excel 관계 정보는 최대 2,048개까지 허용됩니다."
                )
            rel_id = node.attrib.get("Id", "")
            rel_type = node.attrib.get("Type", "")
            target = node.attrib.get("Target", "")
            target_mode = node.attrib.get("TargetMode", "")
            if target_mode.casefold() == "external":
                raise SpreadsheetInputError(
                    "외부 파일이나 인터넷 주소에 연결된 Excel 관계를 거부했습니다."
                )
            # 관계 URL 전체를 부분 문자열로 검사하면 정상 OPC namespace의
            # ``.../package/.../core-properties``까지 내장 package로 오인한다.
            # OOXML 관계 종류의 마지막 path token만 정확히 비교한다.
            relation_type_name = rel_type.rstrip("/").rsplit("/", 1)[-1].casefold()
            if relation_type_name in _DANGEROUS_RELATIONSHIP_TYPE_NAMES:
                raise SpreadsheetInputError(
                    "매크로·ActiveX·내장 개체 관계가 포함된 Excel 파일은 읽을 수 없습니다."
                )
            if not rel_id or rel_id in entries or not rel_type or not target:
                raise SpreadsheetInputError(
                    f"Excel 관계 정보가 올바르지 않습니다: {name}"
                )
            target_part = _resolve_relationship_target(source_part, target)
            entries[rel_id] = _Relationship(rel_id, rel_type, target_part)
        result[name] = entries
    return result


def _source_part_for_relationships(rels_name: str) -> str:
    if rels_name == "_rels/.rels":
        return ""
    path = PurePosixPath(rels_name)
    if path.parent.name != "_rels" or not path.name.endswith(".rels"):
        raise SpreadsheetInputError(f"Excel 관계 경로가 올바르지 않습니다: {rels_name}")
    original_name = path.name[: -len(".rels")]
    return str(path.parent.parent / original_name)


def _resolve_relationship_target(source_part: str, target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise SpreadsheetInputError(
            f"Excel 내부 관계 대상이 안전하지 않습니다: {target}"
        )
    decoded = unquote(parsed.path)
    if "\x00" in decoded or "\\" in decoded or _DRIVE_PATH_RE.match(decoded):
        raise SpreadsheetInputError(
            f"Excel 내부 관계 대상이 안전하지 않습니다: {target}"
        )
    if decoded.startswith("/"):
        combined = decoded.lstrip("/")
    else:
        combined = posixpath.join(posixpath.dirname(source_part), decoded)
    normalized = posixpath.normpath(combined)
    if (
        not normalized
        or normalized == "."
        or normalized == ".."
        or normalized.startswith("../")
        or normalized.startswith("/")
    ):
        raise SpreadsheetInputError(
            f"Excel 내부 관계 대상이 안전하지 않습니다: {target}"
        )
    return normalized


def _validate_content_types(raw: bytes) -> None:
    root = _parse_xml_part(raw, "[Content_Types].xml")
    if _local_name(root.tag) != "Types":
        raise SpreadsheetInputError("Excel Content Types XML이 올바르지 않습니다.")
    workbook_type = ""
    default_xml_type = ""
    for node in root.iter():
        content_type = node.attrib.get("ContentType", "")
        lowered = content_type.casefold()
        if any(marker in lowered for marker in _DANGEROUS_CONTENT_TYPE_MARKERS):
            raise SpreadsheetInputError(
                "매크로·ActiveX·내장 개체가 포함된 Excel 파일은 읽을 수 없습니다."
            )
        if node.attrib.get("PartName", "").lstrip("/") == "xl/workbook.xml":
            workbook_type = content_type
        if node.attrib.get("Extension", "").casefold() == "xml":
            default_xml_type = content_type
    # OOXML writers commonly use a workbook Override, while some valid writers
    # make the workbook MIME type the default for .xml and override each other
    # XML part. Resolve both representations as OPC specifies.
    workbook_type = workbook_type or default_xml_type
    if not workbook_type.lower().endswith(".sheet.main+xml"):
        raise SpreadsheetInputError(
            "일반 Excel 통합 문서(.xlsx)가 아닙니다. 매크로 없는 .xlsx로 저장해주세요."
        )


def _validate_root_workbook_relationship(
    relationships: dict[str, dict[str, _Relationship]],
) -> None:
    root_rels = relationships.get("_rels/.rels")
    if root_rels is None:
        raise SpreadsheetInputError("Excel 루트 관계 정보가 없습니다.")
    office_documents = [
        rel
        for rel in root_rels.values()
        if rel.rel_type.lower().endswith("/officedocument")
    ]
    if len(office_documents) != 1 or office_documents[0].target_part != "xl/workbook.xml":
        raise SpreadsheetInputError(
            "Excel 통합문서 시작 위치가 올바르지 않습니다."
        )


class _Sheet:
    __slots__ = ("name", "state", "relationship_id")

    def __init__(self, name: str, state: str, relationship_id: str) -> None:
        self.name = name
        self.state = state
        self.relationship_id = relationship_id


def _read_workbook_sheets(root: ET.Element) -> list[_Sheet]:
    if _local_name(root.tag) != "workbook":
        raise SpreadsheetInputError("Excel 통합문서 XML이 올바르지 않습니다.")
    sheets: list[_Sheet] = []
    for node in root.iter():
        if _local_name(node.tag) != "sheet":
            continue
        if len(sheets) >= _MAX_SHEETS:
            raise SpreadsheetInputError("Excel 시트는 최대 20개까지 사용할 수 있습니다.")
        name = _normalize_string(node.attrib.get("name", ""))
        relation_id = (
            node.attrib.get(f"{{{_RELATIONSHIP_NS}}}id")
            or node.attrib.get(f"{{{_STRICT_RELATIONSHIP_NS}}}id")
            or node.attrib.get("id", "")
        )
        state = node.attrib.get("state", "visible").casefold()
        if not name or not relation_id or state not in {"visible", "hidden", "veryhidden"}:
            raise SpreadsheetInputError("Excel 시트 목록이 올바르지 않습니다.")
        sheets.append(_Sheet(name, state, relation_id))
    if not sheets:
        raise SpreadsheetInputError("Excel 파일에 시트가 없습니다.")
    return sheets


def _select_visible_sheet(sheets: list[_Sheet], *, kind: str) -> _Sheet:
    visible = [sheet for sheet in sheets if sheet.state == "visible"]
    visible_names = [sheet.name for sheet in visible]
    shown = ", ".join(visible_names) if visible_names else "(없음)"
    if len(visible) == 1:
        return visible[0]
    if not visible:
        all_names = ", ".join(sheet.name for sheet in sheets)
        raise SpreadsheetInputError(
            f"보이는 Excel 시트가 없습니다. 시트 목록: {all_names}"
        )

    preferred = (
        {"timeline", "타임라인"}
        if kind == "timeline"
        else {"subtitles", "자막"}
    )
    matches = [
        sheet
        for sheet in visible
        if unicodedata.normalize("NFC", sheet.name).strip().casefold() in preferred
    ]
    if len(matches) == 1:
        return matches[0]
    expected = "timeline 또는 타임라인" if kind == "timeline" else "subtitles 또는 자막"
    if len(matches) > 1:
        matched_names = ", ".join(sheet.name for sheet in matches)
        raise SpreadsheetInputError(
            f"선택할 시트가 여러 개입니다: {matched_names}. 하나만 남기거나 숨겨주세요. "
            f"보이는 시트: {shown}"
        )
    raise SpreadsheetInputError(
        f"보이는 시트가 여러 개라 자동 선택할 수 없습니다. '{expected}' 시트가 필요합니다. "
        f"보이는 시트: {shown}"
    )


def _relationship_by_type(
    relationships: dict[str, _Relationship],
    suffix: str,
) -> _Relationship | None:
    matches = [
        relation
        for relation in relationships.values()
        if relation.rel_type.casefold().endswith("/" + suffix.casefold())
    ]
    if len(matches) > 1:
        raise SpreadsheetInputError(f"Excel {suffix} 관계가 중복되었습니다.")
    return matches[0] if matches else None


def _read_shared_strings(root: ET.Element) -> list[str]:
    if _local_name(root.tag) != "sst":
        raise SpreadsheetInputError("Excel 공유 문자열 XML이 올바르지 않습니다.")
    result: list[str] = []
    for node in root:
        if _local_name(node.tag) != "si":
            continue
        if len(result) >= _MAX_SHARED_STRINGS:
            raise SpreadsheetInputError(
                "Excel 공유 문자열은 최대 100,000개까지 허용됩니다."
            )
        value = _rich_text(node)
        _check_cell_text_limit(value, context="Excel 공유 문자열")
        result.append(value)
    return result


def _read_style_classes(root: ET.Element) -> list[str]:
    if _local_name(root.tag) != "styleSheet":
        raise SpreadsheetInputError("Excel 스타일 XML이 올바르지 않습니다.")
    custom_formats: dict[int, str] = {}
    cell_xfs: ET.Element | None = None
    for node in root.iter():
        local = _local_name(node.tag)
        if local == "numFmt":
            try:
                format_id = int(node.attrib.get("numFmtId", ""))
            except ValueError as exc:
                raise SpreadsheetInputError("Excel 숫자 표시 형식이 손상되었습니다.") from exc
            custom_formats[format_id] = node.attrib.get("formatCode", "")
        elif local == "cellXfs":
            cell_xfs = node

    if cell_xfs is None:
        return ["general"]

    result: list[str] = []
    for xf in cell_xfs:
        if _local_name(xf.tag) != "xf":
            continue
        if len(result) >= _MAX_CELL_STYLES:
            raise SpreadsheetInputError(
                "Excel 셀 스타일은 최대 4,096개까지 허용됩니다."
            )
        try:
            format_id = int(xf.attrib.get("numFmtId", "0"))
        except ValueError as exc:
            raise SpreadsheetInputError("Excel 셀 스타일 번호가 손상되었습니다.") from exc
        result.append(_classify_number_format(format_id, custom_formats.get(format_id)))
    return result or ["general"]


def _classify_number_format(format_id: int, custom_code: str | None) -> str:
    if custom_code is None:
        if format_id in _BUILTIN_DATE_FORMAT_IDS:
            return "date"
        if format_id in _BUILTIN_TIME_FORMAT_IDS:
            return "time"
        return "general"

    code = _format_tokens(custom_code)
    if not code:
        return "general"
    has_year = "y" in code
    has_day = "d" in code
    has_hour = "h" in code or "[h]" in code
    has_second = "s" in code or "[s]" in code
    has_minute = "m" in code or "[m]" in code
    has_elapsed_minute = "[m]" in code
    has_ampm = "am/pm" in code or "a/p" in code
    if has_year or has_day:
        return "date"
    if has_hour or has_second or has_ampm or has_elapsed_minute:
        return "time"
    # 월만 표시하는 형식과 분만 표시하는 형식은 구분할 근거가 없다. 날짜를
    # 시간으로 오인하는 것보다 명확한 오류가 안전하다.
    if has_minute:
        return "date"
    return "general"


def _format_tokens(code: str) -> str:
    first_section = code.split(";", 1)[0]
    output: list[str] = []
    index = 0
    while index < len(first_section):
        char = first_section[index]
        if char == '"':
            index += 1
            while index < len(first_section):
                if first_section[index] == '"':
                    index += 1
                    break
                index += 1
            continue
        if char in {"\\", "_", "*"}:
            index += 2
            continue
        if char == "[":
            end = first_section.find("]", index + 1)
            if end < 0:
                break
            content = first_section[index + 1 : end].strip().casefold()
            if content in {"h", "hh", "m", "mm", "s", "ss"}:
                output.append("[" + content[0] + "]")
            index = end + 1
            continue
        output.append(char.casefold())
        index += 1
    return "".join(output)


def _read_worksheet(
    root: ET.Element,
    *,
    shared_strings: list[str],
    style_classes: list[str],
    max_rows: int,
    sheet_name: str,
) -> list[list[str]]:
    if _local_name(root.tag) != "worksheet":
        raise SpreadsheetInputError(f"'{sheet_name}' 시트 XML이 올바르지 않습니다.")
    if any(_local_name(node.tag) == "mergeCell" for node in root.iter()):
        raise SpreadsheetInputError(
            f"'{sheet_name}' 시트에는 병합 셀을 사용할 수 없습니다. 병합을 해제해주세요."
        )

    cells_by_row: dict[int, dict[int, str]] = {}
    seen_cells: set[tuple[int, int]] = set()
    nonempty_cells = 0
    worksheet_cells = 0
    total_characters = 0

    sheet_data = next(
        (node for node in root.iter() if _local_name(node.tag) == "sheetData"),
        None,
    )
    if sheet_data is None:
        raise SpreadsheetInputError(f"'{sheet_name}' 시트에 표 데이터가 없습니다.")

    inferred_row = 0
    for row_node in sheet_data:
        if _local_name(row_node.tag) != "row":
            continue
        row_attr = row_node.attrib.get("r")
        if row_attr:
            # int() 전에 길이를 제한해 수백만 자리 정수 변환으로 인한 CPU 낭비를 막는다.
            if re.fullmatch(r"[1-9][0-9]{0,6}", row_attr) is None:
                raise SpreadsheetInputError("Excel 행 번호가 손상되었습니다.")
            row_number = int(row_attr)
            if row_number > _MAX_EXCEL_ROW:
                raise SpreadsheetInputError("Excel 행 번호가 허용 범위를 벗어났습니다.")
        else:
            row_number = inferred_row + 1
        if row_number <= inferred_row:
            raise SpreadsheetInputError("Excel 행 순서가 중복되거나 뒤섞여 있습니다.")
        inferred_row = row_number

        inferred_column = 0
        for cell in row_node:
            if _local_name(cell.tag) != "c":
                continue
            worksheet_cells += 1
            if worksheet_cells > _MAX_WORKSHEET_CELLS:
                raise SpreadsheetInputError(
                    "Excel 시트의 셀은 빈 셀을 포함해 최대 100,000개까지 허용됩니다."
                )
            if any(_local_name(node.tag) == "f" for node in cell):
                raise SpreadsheetInputError(
                    f"'{sheet_name}' 시트에는 수식을 사용할 수 없습니다. "
                    "수식 결과를 값으로 붙여넣어주세요."
                )

            reference = cell.attrib.get("r")
            if reference:
                column_number, reference_row = _parse_cell_reference(reference)
                if reference_row != row_number:
                    raise SpreadsheetInputError(
                        f"Excel 셀 주소와 행 번호가 일치하지 않습니다: {reference}"
                    )
            else:
                column_number = inferred_column + 1
            inferred_column = column_number

            coordinate = (row_number, column_number)
            if coordinate in seen_cells:
                raise SpreadsheetInputError(f"Excel 셀 주소가 중복되었습니다: {reference}")
            seen_cells.add(coordinate)

            value = _read_cell_value(
                cell,
                shared_strings=shared_strings,
                style_classes=style_classes,
                reference=reference or f"{row_number}행 {column_number}열",
            )
            if not value:
                continue
            if column_number > _MAX_COLUMNS:
                raise SpreadsheetInputError(
                    f"표는 최대 32열까지 사용할 수 있습니다: {reference}"
                )
            _check_cell_text_limit(value, context=reference or "Excel 셀")
            nonempty_cells += 1
            total_characters += len(value)
            if nonempty_cells > _MAX_NONEMPTY_CELLS:
                raise SpreadsheetInputError("표의 값이 든 셀은 최대 50,000개까지 허용됩니다.")
            if total_characters > _MAX_TOTAL_CHARACTERS:
                raise SpreadsheetInputError("표의 전체 글자 수는 최대 5,000,000자입니다.")
            cells_by_row.setdefault(row_number, {})[column_number] = value

    if 1 not in cells_by_row or not cells_by_row[1]:
        raise SpreadsheetInputError(
            f"'{sheet_name}' 시트의 1행에 열 이름을 적어주세요. "
            "머리글은 반드시 1행이어야 합니다."
        )

    header_width = max(cells_by_row[1])
    if header_width > _MAX_COLUMNS:
        raise SpreadsheetInputError("표는 최대 32열까지 사용할 수 있습니다.")
    header = [cells_by_row[1].get(column, "") for column in range(1, header_width + 1)]

    data_rows: list[list[str]] = []
    for row_number in sorted(number for number in cells_by_row if number != 1):
        values = cells_by_row[row_number]
        rightmost = max(values)
        if rightmost > header_width:
            raise SpreadsheetInputError(
                f"'{sheet_name}' 시트 {row_number}행에 1행 머리글보다 오른쪽 값이 있습니다."
            )
        data_rows.append([values.get(column, "") for column in range(1, header_width + 1)])
        if len(data_rows) > max_rows:
            raise SpreadsheetInputError(
                f"데이터 행은 최대 {max_rows:,}개까지 업로드할 수 있습니다."
            )

    return [header, *data_rows]


def _read_cell_value(
    cell: ET.Element,
    *,
    shared_strings: list[str],
    style_classes: list[str],
    reference: str,
) -> str:
    cell_type = cell.attrib.get("t", "n")
    if cell_type == "e":
        raise SpreadsheetInputError(
            f"오류 값이 든 Excel 셀은 사용할 수 없습니다: {reference}"
        )
    if cell_type == "d":
        raise SpreadsheetInputError(
            f"날짜 형식의 Excel 셀은 사용할 수 없습니다: {reference}. "
            "시간을 00:00:00.000 형식의 텍스트로 입력해주세요."
        )

    style_class = "general"
    style_text = cell.attrib.get("s")
    if style_text is not None:
        try:
            style_index = int(style_text)
        except ValueError as exc:
            raise SpreadsheetInputError(f"Excel 셀 스타일이 손상되었습니다: {reference}") from exc
        if style_index < 0 or style_index >= len(style_classes):
            raise SpreadsheetInputError(f"Excel 셀 스타일이 손상되었습니다: {reference}")
        style_class = style_classes[style_index]

    value_node = next(
        (node for node in cell if _local_name(node.tag) == "v"),
        None,
    )
    raw_value = "" if value_node is None or value_node.text is None else value_node.text

    if cell_type == "inlineStr":
        inline = next(
            (node for node in cell if _local_name(node.tag) == "is"),
            None,
        )
        return _rich_text(inline) if inline is not None else ""
    if cell_type == "s":
        if not raw_value:
            raise SpreadsheetInputError(f"Excel 공유 문자열 셀이 손상되었습니다: {reference}")
        try:
            index = int(raw_value)
        except ValueError as exc:
            raise SpreadsheetInputError(f"Excel 공유 문자열 셀이 손상되었습니다: {reference}") from exc
        if index < 0 or index >= len(shared_strings):
            raise SpreadsheetInputError(f"Excel 공유 문자열 셀이 손상되었습니다: {reference}")
        return shared_strings[index]
    if cell_type == "b":
        if raw_value == "1":
            return "TRUE"
        if raw_value == "0":
            return "FALSE"
        raise SpreadsheetInputError(f"Excel 논리 셀이 손상되었습니다: {reference}")
    if cell_type in {"str", "inlineStr"}:
        return _normalize_string(raw_value)
    if cell_type not in {"n", ""}:
        raise SpreadsheetInputError(
            f"지원하지 않는 Excel 셀 형식입니다: {reference} ({cell_type})"
        )
    if not raw_value:
        return ""
    if style_class == "date":
        raise SpreadsheetInputError(
            f"날짜 형식의 Excel 셀은 사용할 수 없습니다: {reference}. "
            "시간을 00:00:00.000 형식의 텍스트로 입력해주세요."
        )
    number = _parse_decimal(raw_value, reference=reference)
    if style_class == "time":
        if number < 0:
            raise SpreadsheetInputError(
                f"음수 시간은 사용할 수 없습니다: {reference}. "
                "시간을 00:00:00.000 이상의 값으로 입력해주세요."
            )
        return _excel_time_text(number)
    return _decimal_text(number)


def _parse_decimal(value: str, *, reference: str) -> Decimal:
    if len(value) > _MAX_CELL_CHARACTERS:
        raise SpreadsheetInputError(
            f"Excel 숫자 셀이 너무 깁니다(최대 10,000자): {reference}"
        )
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise SpreadsheetInputError(f"Excel 숫자 셀이 손상되었습니다: {reference}") from exc
    if not number.is_finite():
        raise SpreadsheetInputError(f"Excel 숫자 셀이 유한하지 않습니다: {reference}")
    # 실제 Excel 부동소수점 범위를 벗어난 지수는 정상 통합문서가 만들 수
    # 없으며, 고정소수점 문자열이나 정수로 펼칠 때 메모리를 과다 사용한다.
    if number and not -324 <= number.adjusted() <= 308:
        raise SpreadsheetInputError(
            f"Excel에서 표현할 수 있는 숫자 범위를 벗어났습니다: {reference}"
        )
    return number


def _decimal_text(number: Decimal) -> str:
    if number == 0:
        return "0"
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _excel_time_text(days: Decimal) -> str:
    total_milliseconds = int(
        (abs(days) * Decimal(86_400_000)).to_integral_value(rounding=ROUND_HALF_UP)
    )
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    sign = "-" if days < 0 else ""
    return f"{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _parse_cell_reference(reference: str) -> tuple[int, int]:
    match = _CELL_REF_RE.fullmatch(reference)
    if match is None:
        raise SpreadsheetInputError(
            f"Excel 셀 주소가 올바르지 않습니다: {_short_value(reference)}"
        )
    column_letters, row_text = match.groups()
    column_number = 0
    for character in column_letters.upper():
        column_number = column_number * 26 + ord(character) - ord("A") + 1
    row_number = int(row_text)
    if column_number > _MAX_EXCEL_COLUMN or row_number > _MAX_EXCEL_ROW:
        raise SpreadsheetInputError(
            f"Excel 셀 주소가 허용 범위를 벗어났습니다: {_short_value(reference)}"
        )
    return column_number, row_number


def _normalize_table(
    rows: Iterable[list[str]],
    *,
    max_rows: int,
    source: str,
) -> list[list[str]]:
    row_iterator = iter(rows)
    try:
        first_row = next(row_iterator)
    except StopIteration:
        raise SpreadsheetInputError("기획표의 1행에 열 이름을 적어주세요.")

    normalized_header = [_normalize_string(value) for value in first_row]
    while normalized_header and normalized_header[-1] == "":
        normalized_header.pop()
    if not normalized_header or not any(normalized_header):
        raise SpreadsheetInputError(
            "기획표의 1행에 열 이름을 적어주세요. 머리글은 반드시 1행이어야 합니다."
        )

    normalized_rows: list[list[str]] = [normalized_header]
    nonempty_cells = 0
    total_characters = 0
    max_width = len(normalized_header)

    if max_width > _MAX_COLUMNS:
        raise SpreadsheetInputError("표는 최대 32열까지 사용할 수 있습니다.")
    for value in normalized_header:
        if not value:
            continue
        _check_cell_text_limit(value, context=source)
        nonempty_cells += 1
        total_characters += len(value)

    physical_rows = 1
    for original_row in row_iterator:
        physical_rows += 1
        if physical_rows > max_rows * 2 + 1_000:
            raise SpreadsheetInputError(
                "CSV의 빈 행을 포함한 전체 행이 너무 많습니다. 불필요한 빈 행을 지워주세요."
            )
        row = [_normalize_string(value) for value in original_row]
        while row and row[-1] == "":
            row.pop()
        if not row or not any(row):
            continue
        if len(row) > _MAX_COLUMNS:
            raise SpreadsheetInputError("표는 최대 32열까지 사용할 수 있습니다.")
        if len(row) > len(normalized_header):
            raise SpreadsheetInputError(
                "데이터 행에 1행 머리글보다 오른쪽 값이 있습니다. "
                "모든 열의 이름을 1행에 적어주세요."
            )
        for value in row:
            if not value:
                continue
            _check_cell_text_limit(value, context=source)
            nonempty_cells += 1
            total_characters += len(value)
        if nonempty_cells > _MAX_NONEMPTY_CELLS:
            raise SpreadsheetInputError("표의 값이 든 셀은 최대 50,000개까지 허용됩니다.")
        if total_characters > _MAX_TOTAL_CHARACTERS:
            raise SpreadsheetInputError("표의 전체 글자 수는 최대 5,000,000자입니다.")
        max_width = max(max_width, len(row))
        normalized_rows.append(row)
        if len(normalized_rows) - 1 > max_rows:
            raise SpreadsheetInputError(
                f"데이터 행은 최대 {max_rows:,}개까지 업로드할 수 있습니다."
            )

    return [row + [""] * (max_width - len(row)) for row in normalized_rows]


def _canonical_csv(rows: list[list[str]]) -> tuple[str, bytes]:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    text = buffer.getvalue()
    return text, b"\xef\xbb\xbf" + text.encode("utf-8")


def _rich_text(node: ET.Element) -> str:
    pieces = [
        descendant.text or ""
        for descendant in node.iter()
        if _local_name(descendant.tag) == "t"
    ]
    return _normalize_string("".join(pieces))


def _normalize_string(value: object) -> str:
    text = str(value if value is not None else "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text:
        raise SpreadsheetInputError("표 셀에 NUL 제어 문자를 사용할 수 없습니다.")
    return unicodedata.normalize("NFC", text)


def _check_cell_text_limit(value: str, *, context: str) -> None:
    if len(value) > _MAX_CELL_CHARACTERS:
        raise SpreadsheetInputError(
            f"셀 하나에는 최대 10,000자까지 입력할 수 있습니다: {context}"
        )


def _short_value(value: object, limit: int = 120) -> str:
    """오류 메시지가 공격자 입력 전체를 출력하지 않도록 짧게 표시한다."""

    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


__all__ = [
    "NUMBERS_EXPORT_GUIDANCE",
    "PlanInputError",
    "SUPPORTED_EXTENSIONS",
    "SpreadsheetInputError",
    "decode_uploaded_plan",
]
