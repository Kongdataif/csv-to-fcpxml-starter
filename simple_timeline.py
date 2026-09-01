#!/usr/bin/env python3
"""초보자용 순차 편집 CSV를 정밀 ``timeline.csv``로 변환한다.

이 모듈은 사용자가 Final Cut의 타임라인 시간을 직접 계산하지 않아도 되게
하는 작은 어댑터다. 사용자는 사진과 영상을 한 표에 섞어서 적을 수 있고,
코드는 파일 확장자로 종류를 판단한 뒤 각 행의 길이를 앞에서부터 누적한다.

중요한 설계 원칙
------------------
* ``영상 원본 시작``/``영상 원본 끝``은 *원본 영상 안에서 사용할 구간*이다.
* 사진에는 원본 시간이 없으므로 ``사진 표시 시간(초)``만 사용한다.
* ``음량 dB``처럼 초보자가 계산하기 어려운 값은 입력받지 않는다.
* 결과 CSV는 기존 :mod:`csv_to_fcpxml` 엔진이 그대로 읽을 수 있는 정밀
  형식이다. 즉, 이 파일은 UI/Colab 입력과 검증된 생성 엔진 사이의 경계다.

외부 패키지는 사용하지 않는다. CSV 출력은 ``csv.DictWriter``로 인용 부호를
안전하게 처리하고, 실제 파일 교체는 기존 엔진의 원자적 쓰기 함수를 쓴다.
"""

from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Mapping

import csv_to_fcpxml as engine


# 이 표만 수정하면 Colab UI에서 허용할 쉬운 한국어 표현을 늘릴 수 있다.
# 키 비교 전에 앞뒤 공백을 없애고 영문은 소문자로 바꾸므로 ``ON``도 허용된다.
AUDIO_LABELS: Mapping[str, bool] = {
    "사용": True,
    "켜기": True,
    "원본": True,
    "원본 소리": True,
    "예": True,
    "on": True,
    "yes": True,
    "true": True,
    "끄기": False,
    "미사용": False,
    "음소거": False,
    "아니오": False,
    "off": False,
    "no": False,
    "false": False,
}


# 화면 맞춤도 기술 용어(fit/fill/none)와 사용자 문구를 한곳에서 매핑한다.
CONFORM_LABELS: Mapping[str, str] = {
    "": "fit",
    "전체 보이기": "fit",
    "전체 보기": "fit",
    "fit": "fit",
    "채우기": "fill",
    "화면 채우기": "fill",
    "fill": "fill",
    "원본": "none",
    "자동 맞춤 안 함": "none",
    "맞춤 안 함": "none",
    "none": "none",
}


BEGINNER_HEADERS = {
    "순서",
    "파일",
    "영상 원본 시작",
    "영상 원본 끝",
    "사진 표시 시간(초)",
    "화면 자막",
    "소리",
    "화면 맞춤",
    "세로 화면 맞춤",
    "가로 화면 맞춤",
    "메모",
}

# 화면 방향은 기획표의 필수 열이 아니다. 호출자가 만드는 프로젝트 방향에
# 맞는 열만 고르고, 그 셀이 비어 있으면 기존 공통 ``화면 맞춤``으로 돌아간다.
# 이렇게 하면 기본 6열 양식은 그대로 쓰면서 필요한 장면만 방향별로 조정할
# 수 있다.
LAYOUT_CONFORM_HEADERS: Mapping[str, str] = {
    "portrait": "세로 화면 맞춤",
    "landscape": "가로 화면 맞춤",
}

# 기존 엔진이 읽는 정밀 CSV의 열 이름과 호환 별칭이다. ``시작``/``끝``은
# 예전 간편 모드에서는 '완성 타임라인 위치'였으므로 정밀 형식으로 판정한다.
_FILE_HEADERS = {"file", "filename", "파일", "media", "source"}
_TIMELINE_IN_HEADERS = {"timeline_in", "output in", "output_in", "타임라인 시작", "시작", "in"}
_TIMELINE_OUT_HEADERS = {"timeline_out", "output out", "output_out", "타임라인 끝", "끝", "out"}

PRECISION_TIMELINE_HEADERS = (
    "id",
    "kind",
    "file",
    "timeline_in",
    "timeline_out",
    "source_in",
    "source_out",
    "conform",
    "include_audio",
    "volume_db",
    "notes",
)

GENERATED_SUBTITLE_HEADERS = ("번호", "시작", "끝", "최종 대사", "장면 의도")


@dataclass(frozen=True)
class SimpleTimelineSummary:
    """Colab 결과 화면에 바로 표시할 수 있는 변환 요약.

    ``total_duration``은 오차가 생기지 않는 :class:`fractions.Fraction`이다.
    UI에서는 ``csv_to_fcpxml.display_time``으로 보기 좋게 표시하면 된다.
    """

    timeline_csv: Path
    subtitles_csv: Path | None
    mode: str
    clip_count: int
    video_count: int
    image_count: int
    subtitle_count: int
    total_duration: Fraction
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _SourceRow:
    """CSV 한 행과 실제 파일을 함께 보관하는 내부 모델."""

    row_number: int
    order: int
    values: dict[str, str]
    file_path: Path
    kind: str
    filename_warning: str | None = None


def _header_key(value: object) -> str:
    """BOM/유니코드 조합 차이와 불필요한 공백을 없앤 헤더 비교 키."""

    return unicodedata.normalize("NFC", str(value or "")).strip().lower()


def _cell(value: object) -> str:
    """셀 값을 문자열로 바꾸되 실제 파일명의 Unicode 표기는 보존한다.

    macOS 파일명은 한글이 NFD 형태일 수 있다. 셀 전체를 NFC로 바꾸면 눈에는
    같은 파일도 더는 정확히 찾을 수 없으므로 값은 앞뒤 공백만 제거한다.
    소리/맞춤 같은 선택값은 사용할 때 ``_header_key``로 별도 정규화한다.
    """

    return str(value or "").strip()


def detect_header_mode(fieldnames: Iterable[str] | None) -> str:
    """헤더만 보고 ``beginner`` 또는 ``precision``을 반환한다.

    정밀 타임라인 열이 한쪽만 있을 때 beginner로 잘못 해석하지 않고 즉시
    설명 가능한 오류를 낸다. 이 함수는 Colab에서 업로드 직후 모드를 표시할
    때도 사용할 수 있다.
    """

    if not fieldnames:
        raise engine.BuildError("CSV 헤더가 없습니다. 첫 줄에 열 이름을 적어주세요.")

    normalized = [_header_key(name) for name in fieldnames]
    if any(not name for name in normalized):
        raise engine.BuildError("CSV 헤더에 이름이 비어 있는 열이 있습니다.")
    if len(normalized) != len(set(normalized)):
        raise engine.BuildError("CSV 헤더에 같은 이름의 열이 두 번 있습니다.")

    names = set(normalized)
    if not names.intersection(_FILE_HEADERS):
        raise engine.BuildError("CSV에 필수 열 '파일'이 없습니다.")

    has_timeline_in = bool(names.intersection(_TIMELINE_IN_HEADERS))
    has_timeline_out = bool(names.intersection(_TIMELINE_OUT_HEADERS))
    if has_timeline_in != has_timeline_out:
        raise engine.BuildError(
            "정밀 CSV의 타임라인 시작/끝 열은 항상 함께 있어야 합니다. "
            "두 열을 모두 넣거나 모두 빼주세요."
        )
    if has_timeline_in and has_timeline_out:
        return "precision"

    # 초보자 양식은 의도적으로 한국어 '파일' 열을 요구한다. 영문 file 하나만
    # 있는 불완전한 정밀 CSV를 beginner로 오인하는 일을 막기 위해서다.
    if "파일" not in names:
        raise engine.BuildError(
            "간편 CSV의 필수 열 이름은 '파일'입니다. 정밀 CSV라면 "
            "timeline_in과 timeline_out 열도 함께 넣어주세요."
        )
    return "beginner"


def detect_csv_mode(path: str | Path) -> str:
    """CSV 파일을 열어 입력 모드를 판정한다."""

    csv_path = Path(path)
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return detect_header_mode(csv.reader(handle).__next__())
    except FileNotFoundError as exc:
        raise engine.BuildError(f"CSV 파일을 찾지 못했습니다: {csv_path}") from exc
    except StopIteration as exc:
        raise engine.BuildError("CSV가 비어 있습니다. 첫 줄에 열 이름을 적어주세요.") from exc
    except UnicodeDecodeError as exc:
        raise engine.BuildError("CSV를 UTF-8 형식으로 저장한 뒤 다시 업로드해주세요.") from exc


def _positive_duration(value: Fraction | int | float | str, *, field: str) -> Fraction:
    """초 단위 숫자를 양의 Fraction으로 바꾸고 사용자용 오류를 만든다."""

    try:
        # Fraction은 이미 정확한 값이므로 ``3/2`` 문자열로 바꾸지 않는다.
        # 그 밖의 입력은 엔진 공통 숫자 파서를 사용해 NaN/Infinity도 차단한다.
        duration = value if isinstance(value, Fraction) else engine.decimal_to_fraction(value)
    except engine.BuildError as exc:
        raise engine.BuildError(f"{field}: 초 단위 숫자를 입력해주세요. 현재 값: {value!r}") from exc
    if duration <= 0:
        raise engine.BuildError(f"{field}: 0보다 큰 초를 입력해주세요. 현재 값: {value!r}")
    return duration


def _format_seconds(value: Fraction) -> str:
    """기존 시간 파서가 읽을 수 있는 소수 초 문자열을 만든다.

    ffprobe 시간은 보통 유한 소수다. 만약 분모가 다른 유리수가 들어와도 9자리
    소수로 반올림해 충분히 정밀하게 넘기며, 실제 엔진이 다시 프레임 경계로
    보정한다.
    """

    if value.denominator == 1:
        return str(value.numerator)
    # float로 바꾸면 긴 영상에서 이진 부동소수점 오차가 생길 수 있으므로
    # Decimal 나눗셈으로 사람이 읽을 수 있는 최대 9자리 소수만 만든다.
    with localcontext() as context:
        context.prec = 40
        decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
        rendered = format(decimal_value, ".9f").rstrip("0").rstrip(".")
    return rendered or "0"


def _write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[Mapping[str, object]]) -> None:
    """쉼표·줄바꿈이 든 파일명/자막도 깨지지 않게 CSV를 원자적으로 쓴다."""

    columns = tuple(fieldnames)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    engine.atomic_write_text(path, buffer.getvalue())


def _read_beginner_rows(input_csv: Path, media_root: Path) -> list[_SourceRow]:
    """간편 CSV를 읽고 순서·파일명·미디어 종류를 먼저 확정한다."""

    try:
        handle = input_csv.open("r", encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise engine.BuildError(f"CSV 파일을 찾지 못했습니다: {input_csv}") from exc

    rows: list[_SourceRow] = []
    try:
        with handle:
            reader = csv.DictReader(handle)
            mode = detect_header_mode(reader.fieldnames)
            if mode != "beginner":
                raise engine.BuildError(
                    "이 파일은 정밀 timeline.csv 형식입니다. 간편 변환을 거치지 말고 "
                    "기존 정밀 모드로 실행해주세요."
                )

            assert reader.fieldnames is not None  # detect_header_mode에서 이미 검사함
            header_map = {_header_key(name): name for name in reader.fieldnames}
            unknown = sorted(set(header_map).difference(BEGINNER_HEADERS))
            if unknown:
                raise engine.BuildError(
                    "간편 CSV에서 알 수 없는 열을 발견했습니다: "
                    + ", ".join(repr(name) for name in unknown)
                    + ". 제공된 양식의 열 이름을 그대로 사용해주세요."
                )

            has_order_column = "순서" in header_map
            seen_orders: dict[int, int] = {}
            root = media_root.resolve()

            for row_number, raw_row in enumerate(reader, start=2):
                if None in raw_row:
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: 헤더보다 값이 많습니다. "
                        "쉼표가 든 문장은 큰따옴표로 감싸주세요."
                    )
                values = {_header_key(key): _cell(value) for key, value in raw_row.items()}
                if not any(values.values()):
                    continue

                file_text = values.get("파일", "")
                if not file_text:
                    raise engine.BuildError(f"간편 CSV {row_number}행: '파일' 값이 비어 있습니다.")

                # 업로드 화면의 파일명과 정확히 1:1로 대응시키기 위해 폴더 경로를
                # 받지 않는다. 이 제한은 ../ 경로 탈출도 함께 차단한다.
                candidate_name = Path(file_text)
                if (
                    candidate_name.is_absolute()
                    or candidate_name.name != file_text
                    or "/" in file_text
                    or "\\" in file_text
                    or file_text in {".", ".."}
                ):
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: '파일'에는 폴더 경로가 아닌 "
                        f"업로드한 파일명만 적어주세요. 현재 값: {file_text!r}"
                    )

                filename_warning: str | None = None
                # macOS의 기본 파일시스템은 대소문자와 NFC/NFD 표기를 동등하게
                # 취급할 수 있다. ``root / file_text``의 존재 여부를 먼저 물으면
                # 실제 업로드 이름이 달라도 성공하므로, 디렉터리가 보관한 이름을
                # 먼저 비교해 모든 플랫폼에서 같은 규칙을 적용한다.
                entries = list(root.iterdir()) if root.is_dir() else []
                exact_matches = [item for item in entries if item.name == file_text]
                canonical_name = unicodedata.normalize("NFC", file_text)
                canonical_matches = [
                    item
                    for item in entries
                    if unicodedata.normalize("NFC", item.name) == canonical_name
                ]

                actual_item: Path | None
                if exact_matches:
                    actual_item = exact_matches[0]
                elif len(canonical_matches) == 1:
                    actual_item = canonical_matches[0]
                    filename_warning = (
                        f"간편 CSV {row_number}행: Unicode 표기만 다른 파일명을 "
                        f"실제 업로드 이름 {actual_item.name!r}에 자동 연결했습니다."
                    )
                elif len(canonical_matches) > 1:
                    candidates = ", ".join(repr(item.name) for item in canonical_matches)
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: 화면에는 같아 보이는 파일명이 여러 개입니다: "
                        f"{candidates}. 중복 파일명을 정리한 뒤 다시 업로드해주세요."
                    )
                else:
                    actual_item = None

                if actual_item is None:
                    # 대소문자만 다른 파일을 별도로 알려주면 Windows에서 만든 CSV를
                    # Mac이나 Linux 기반 Colab에 올렸을 때 원인을 바로 이해할 수 있다.
                    case_matches = [
                        item.name
                        for item in entries
                        if unicodedata.normalize("NFC", item.name).casefold()
                        == canonical_name.casefold()
                    ]
                    if case_matches:
                        detail = (
                            f" 업로드된 이름은 {case_matches[0]!r}입니다. "
                            "대소문자까지 같게 적어주세요."
                        )
                    else:
                        detail = " CSV의 파일명과 업로드한 파일명(확장자 포함)을 똑같이 적어주세요."
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: Media 폴더에서 {file_text!r} 파일을 찾지 못했습니다.{detail}"
                    )

                # ``is_file``은 심볼릭 링크를 따라가므로 링크 자체를 먼저
                # 거부한다. 그렇지 않으면 Media/evil.mov -> /outside/secret.mov
                # 같은 링크가 ffprobe 단계에서 외부 파일을 읽을 수 있다.
                if actual_item.is_symlink():
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: 심볼릭 링크는 미디어로 사용할 수 없습니다: "
                        f"{file_text!r}. 실제 사진/영상 파일을 직접 업로드해주세요."
                    )
                if not actual_item.is_file():
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: {file_text!r}은 일반 미디어 파일이 아닙니다. "
                        "폴더나 특수 파일 대신 실제 사진/영상을 업로드해주세요."
                    )
                file_path = actual_item.resolve(strict=True)

                # 파일을 연 뒤가 아니라 probe *전에* 실제 해석된 경로의 범위를
                # 다시 확인한다. 심볼릭 링크 외의 플랫폼별 경로 변형에도 대비한다.
                if file_path == root or root not in file_path.parents:
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: 미디어 파일은 Media 폴더 안에 있어야 합니다: "
                        f"{file_text!r}"
                    )

                try:
                    kind = engine.infer_kind(file_path)
                except engine.BuildError as exc:
                    raise engine.BuildError(f"간편 CSV {row_number}행: {exc}") from exc
                if kind not in {"video", "image"}:
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: {file_text!r}은 사진 또는 영상이 아닙니다. "
                        "오디오 파일만 단독 장면으로 넣을 수는 없습니다."
                    )

                if has_order_column:
                    order_text = values.get("순서", "")
                    try:
                        order = int(order_text)
                    except ValueError as exc:
                        raise engine.BuildError(
                            f"간편 CSV {row_number}행: '순서'에는 1 이상의 정수를 입력해주세요. "
                            f"현재 값: {order_text!r}"
                        ) from exc
                    if order <= 0:
                        raise engine.BuildError(
                            f"간편 CSV {row_number}행: '순서'는 1 이상이어야 합니다. 현재 값: {order}"
                        )
                    if order in seen_orders:
                        raise engine.BuildError(
                            f"간편 CSV {row_number}행: 순서 {order}이 중복되었습니다. "
                            f"먼저 사용한 행은 {seen_orders[order]}행입니다."
                        )
                    seen_orders[order] = row_number
                else:
                    # 순서 열이 없으면 CSV에 보이는 행 순서를 그대로 사용한다.
                    order = row_number - 1

                rows.append(
                    _SourceRow(
                        row_number=row_number,
                        order=order,
                        values=values,
                        file_path=file_path,
                        kind=kind,
                        filename_warning=filename_warning,
                    )
                )
    except UnicodeDecodeError as exc:
        raise engine.BuildError("CSV를 UTF-8 형식으로 저장한 뒤 다시 업로드해주세요.") from exc

    if not rows:
        raise engine.BuildError("간편 CSV에 편집할 장면이 없습니다. 파일 행을 한 개 이상 적어주세요.")
    rows.sort(key=lambda item: item.order)
    return rows


def build_simple_timeline(
    input_csv: str | Path,
    media_root: str | Path,
    output_timeline: str | Path,
    output_subtitles: str | Path | None = None,
    default_photo_duration: Fraction | int | float | str = Fraction(3),
    fps: Fraction | int | float | str = Fraction(30),
    layout: str = "portrait",
) -> SimpleTimelineSummary:
    """간편 CSV를 기존 엔진용 정밀 타임라인과 선택 자막 CSV로 변환한다.

    Parameters
    ----------
    input_csv:
        사용자가 작성한 간편 CSV. ``파일`` 열은 필수다.
    media_root:
        업로드된 사진과 영상이 직접 들어 있는 폴더.
    output_timeline:
        생성할 정밀 ``timeline.csv`` 경로. 호출자가 명시적으로 정한다.
    output_subtitles:
        ``화면 자막``이 있을 때 생성할 자막 CSV 경로. 자막이 존재하는데 이
        값이 없으면 조용히 누락하지 않고 오류를 낸다.
    default_photo_duration:
        사진 행의 시간이 비었을 때 사용할 초. Colab 설정 셀에서 정한다.
    fps:
        완성 프로젝트의 초당 프레임 수. 각 장면 길이를 이 프레임 경계에
        반올림한 뒤 정수 프레임 수로 누적하므로 장면이 많아져도 오차가
        쌓이지 않는다. ``29.97``은 엔진 규칙에 따라 30000/1001로 처리된다.
    layout:
        생성할 화면 방향. ``portrait``이면 ``세로 화면 맞춤``을,
        ``landscape``이면 ``가로 화면 맞춤``을 먼저 사용한다. 해당 셀이
        비어 있으면 공통 ``화면 맞춤`` 값을 사용한다.

    Returns
    -------
    SimpleTimelineSummary
        파일 수, 종류, 전체 길이, 경고와 실제 출력 경로.
    """

    source_path = Path(input_csv)
    media_path = Path(media_root)
    timeline_path = Path(output_timeline)
    subtitle_path = Path(output_subtitles) if output_subtitles is not None else None

    normalized_layout = _header_key(layout)
    if normalized_layout not in LAYOUT_CONFORM_HEADERS:
        raise engine.BuildError(
            "layout은 'portrait'(세로) 또는 'landscape'(가로)여야 합니다. "
            f"현재 값: {layout!r}"
        )
    layout_conform_header = LAYOUT_CONFORM_HEADERS[normalized_layout]

    if not media_path.is_dir():
        raise engine.BuildError(f"미디어 폴더를 찾지 못했습니다: {media_path}")

    default_duration = _positive_duration(default_photo_duration, field="기본 사진 표시 시간")
    project_fps = engine.parse_fps(fps)
    source_rows = _read_beginner_rows(source_path, media_path)

    # 동일 영상을 여러 번 잘라 쓸 수 있으므로 ffprobe 결과는 파일별로 한 번만
    # 구한다. 사진은 시간 스트림이 없으므로 probe하지 않는다.
    probe_cache: dict[Path, engine.MediaInfo] = {}
    timeline_rows: list[dict[str, object]] = []
    subtitle_rows: list[dict[str, object]] = []
    warnings: list[str] = [
        source.filename_warning
        for source in source_rows
        if source.filename_warning is not None
    ]
    cursor = Fraction(0)
    video_count = 0
    image_count = 0

    for clip_index, source in enumerate(source_rows, start=1):
        row_number = source.row_number
        values = source.values
        source_in_text = values.get("영상 원본 시작", "")
        source_out_text = values.get("영상 원본 끝", "")
        photo_duration_text = values.get("사진 표시 시간(초)", "")
        audio_text = values.get("소리", "")

        if source.kind == "video":
            video_count += 1
            if photo_duration_text:
                raise engine.BuildError(
                    f"간편 CSV {row_number}행: 영상에는 '사진 표시 시간(초)'을 입력할 수 없습니다. "
                    "영상 길이를 바꾸려면 '영상 원본 시작'과 '영상 원본 끝'으로 사용할 구간을 지정해주세요."
                )
            if bool(source_in_text) != bool(source_out_text):
                raise engine.BuildError(
                    f"간편 CSV {row_number}행: '영상 원본 시작'과 '영상 원본 끝'은 "
                    "둘 다 입력하거나 둘 다 비워주세요."
                )

            try:
                if source.file_path not in probe_cache:
                    probe_cache[source.file_path] = engine.probe_media(source.file_path)
                info = probe_cache[source.file_path]
            except engine.BuildError as exc:
                raise engine.BuildError(
                    f"간편 CSV {row_number}행: 영상 {source.file_path.name!r}을 검사하지 못했습니다. {exc}"
                ) from exc
            if not info.has_video:
                raise engine.BuildError(
                    f"간편 CSV {row_number}행: {source.file_path.name!r}에서 영상 스트림을 찾지 못했습니다."
                )
            media_duration = info.video_duration or info.duration
            if media_duration is None or media_duration <= 0:
                raise engine.BuildError(
                    f"간편 CSV {row_number}행: {source.file_path.name!r}의 영상 길이를 확인할 수 없습니다."
                )

            if source_in_text:
                source_in = engine.parse_time(
                    source_in_text, field=f"간편 CSV {row_number}행 '영상 원본 시작'"
                )
                source_out = engine.parse_time(
                    source_out_text, field=f"간편 CSV {row_number}행 '영상 원본 끝'"
                )
                if source_out <= source_in:
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: '영상 원본 끝'은 '영상 원본 시작'보다 뒤여야 합니다."
                    )
                if source_out > media_duration:
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: 지정한 원본 끝({engine.display_time(source_out)})이 "
                        f"영상 길이({engine.display_time(media_duration)})를 넘습니다."
                    )
            else:
                # 두 칸을 비우면 영상 전체를 사용한다. 이것이 probe가 반드시
                # 필요한 이유이며 사용자가 영상 길이를 직접 알아낼 필요가 없다.
                source_in = Fraction(0)
                source_out = media_duration

            # 기존 생성 엔진도 나중에 같은 보정을 수행한다. 여기서 먼저 원본
            # 영상 FPS에 맞춰야 그 결과로 clip duration을 계산하고, 이어서
            # 프로젝트 FPS에 맞춘 타임라인 길이를 안전하게 만들 수 있다.
            if info.fps:
                snapped_source_in, _, source_in_error = engine.snap_to_frame(source_in, info.fps)
                snapped_source_out, _, source_out_error = engine.snap_to_frame(source_out, info.fps)

                # 파일 끝의 메타데이터가 프레임 경계보다 아주 짧게 기록된 경우,
                # nearest 보정이 실제 duration을 프로젝트 반 프레임 이상 넘지
                # 않도록 마지막 완전한 원본 프레임으로 내린다.
                project_half_frame = Fraction(1, 2) / project_fps
                if snapped_source_out > media_duration + project_half_frame:
                    last_complete_frame = int(media_duration * info.fps)
                    snapped_source_out = Fraction(last_complete_frame, 1) / info.fps
                    source_out_error = abs(snapped_source_out - source_out)

                if snapped_source_out <= snapped_source_in:
                    raise engine.BuildError(
                        f"간편 CSV {row_number}행: 원본 {info.fps}fps 프레임으로 보정한 뒤 "
                        "사용 구간이 1프레임보다 짧습니다. 구간을 늘려주세요."
                    )
                if source_in_error or source_out_error:
                    warnings.append(
                        f"간편 CSV {row_number}행: 영상 원본 구간을 {info.fps}fps 프레임 "
                        f"경계로 보정했습니다 ({engine.display_time(source_in)}–"
                        f"{engine.display_time(source_out)} → "
                        f"{engine.display_time(snapped_source_in)}–"
                        f"{engine.display_time(snapped_source_out)})."
                    )
                source_in, source_out = snapped_source_in, snapped_source_out
            duration = source_out - source_in

            normalized_audio = _header_key(audio_text)
            if not normalized_audio:
                include_audio = True
            elif normalized_audio in AUDIO_LABELS:
                include_audio = AUDIO_LABELS[normalized_audio]
            else:
                allowed = "사용, 끄기"
                raise engine.BuildError(
                    f"간편 CSV {row_number}행: '소리' 값은 {allowed} 중 하나로 적거나 비워주세요. "
                    f"현재 값: {audio_text!r}"
                )
        else:
            image_count += 1
            if source_in_text or source_out_text:
                raise engine.BuildError(
                    f"간편 CSV {row_number}행: 사진에는 '영상 원본 시작/끝'을 입력할 수 없습니다. "
                    "대신 '사진 표시 시간(초)'을 입력해주세요."
                )
            duration = (
                _positive_duration(
                    photo_duration_text,
                    field=f"간편 CSV {row_number}행 '사진 표시 시간(초)'",
                )
                if photo_duration_text
                else default_duration
            )
            source_in = Fraction(0)
            source_out = duration
            include_audio = False
            if audio_text:
                # 표 전체에 같은 값을 채운 사용자에게 수정을 강요하지 않는다.
                # 사진에는 음원이 없으므로 값을 무시했다는 사실만 결과에 남긴다.
                warnings.append(
                    f"간편 CSV {row_number}행: 사진 {source.file_path.name!r}의 '소리' 값은 무시했습니다."
                )

        # 타임라인은 반드시 정수 프로젝트 프레임으로 누적한다. 각 endpoint를
        # 독립적으로 반올림하면 수십 개 장면에서 경계가 밀릴 수 있기 때문에,
        # '이 장면의 프레임 수'를 먼저 구하고 cursor에 더하는 방식이다.
        snapped_duration, frame_count, duration_error = engine.snap_to_frame(duration, project_fps)
        if frame_count < 1:
            raise engine.BuildError(
                f"간편 CSV {row_number}행: 장면 길이 {float(duration):.6f}초는 "
                f"{project_fps}fps에서 1프레임보다 짧습니다. 길이를 늘려주세요."
            )
        if duration_error:
            warnings.append(
                f"간편 CSV {row_number}행: 장면 길이를 {project_fps}fps 프레임 경계로 "
                f"보정했습니다 ({float(duration):.6f}초 → {frame_count}프레임, "
                f"{float(snapped_duration):.6f}초)."
            )

        # 방향별 셀에 값이 있을 때만 공통 설정을 덮어쓴다. 사용자가 기본
        # 6열 양식을 그대로 쓰거나 선택 열을 비워 둔 경우에는 이전 버전과
        # 동일하게 공통 ``화면 맞춤``(없으면 전체 보이기)을 적용한다.
        layout_conform_value = values.get(layout_conform_header, "")
        conform_header = layout_conform_header if layout_conform_value else "화면 맞춤"
        conform_value = layout_conform_value or values.get("화면 맞춤", "")
        conform_text = _header_key(conform_value)
        if conform_text not in CONFORM_LABELS:
            raise engine.BuildError(
                f"간편 CSV {row_number}행: '{conform_header}'은 전체 보이기, 화면 채우기, "
                f"자동 맞춤 안 함 중 하나로 적거나 비워주세요. 현재 값: {conform_value!r}"
            )
        conform = CONFORM_LABELS[conform_text]
        if source.kind == "image" and conform == "none":
            # Still images are rendered into portable H.264 cache clips before
            # FCPXML import.  A literal 'none' at that stage has no stable
            # cross-machine meaning, so make the existing safe-fit behavior
            # explicit instead of silently claiming no conform was preserved.
            conform = "fit"
            warnings.append(
                f"간편 CSV {row_number}행: 사진의 '자동 맞춤 안 함/원본'은 이동 가능한 "
                "캐시를 만들기 위해 '전체 보이기'로 처리했습니다."
            )
        timeline_in = cursor
        timeline_out = cursor + snapped_duration
        clip_id = f"clip_{clip_index:03d}"

        timeline_rows.append(
            {
                "id": clip_id,
                "kind": source.kind,
                "file": source.file_path.name,
                "timeline_in": _format_seconds(timeline_in),
                "timeline_out": _format_seconds(timeline_out),
                "source_in": _format_seconds(source_in),
                # 사진에는 원본 타임코드가 없으므로 프레임 보정된 타임라인
                # 길이를 source_out에도 쓴다. 영상은 실제 원본 trim을 보존한다.
                "source_out": _format_seconds(
                    snapped_duration if source.kind == "image" else source_out
                ),
                "conform": conform,
                "include_audio": "true" if include_audio else "false",
                # 초보자 표에는 dB 열이 없다. 0 dB는 원본 레벨 유지이며,
                # 소리 사용 여부는 include_audio가 전담한다.
                "volume_db": "0",
                "notes": values.get("메모", ""),
            }
        )

        title_text = values.get("화면 자막", "")
        if title_text:
            subtitle_rows.append(
                {
                    "번호": f"S{len(subtitle_rows) + 1:03d}",
                    "시작": _format_seconds(timeline_in),
                    "끝": _format_seconds(timeline_out),
                    "최종 대사": title_text,
                    "장면 의도": values.get("메모", ""),
                }
            )
        cursor = timeline_out

    if subtitle_rows and subtitle_path is None:
        raise engine.BuildError(
            "'화면 자막'이 입력되어 있지만 자막 출력 경로가 지정되지 않았습니다. "
            "output_subtitles 경로를 설정해주세요."
        )
    if subtitle_rows and subtitle_path is not None and subtitle_path.resolve() == timeline_path.resolve():
        raise engine.BuildError("타임라인 CSV와 자막 CSV는 서로 다른 출력 경로여야 합니다.")

    _write_csv(timeline_path, PRECISION_TIMELINE_HEADERS, timeline_rows)
    written_subtitle_path: Path | None = None
    if subtitle_rows and subtitle_path is not None:
        _write_csv(subtitle_path, GENERATED_SUBTITLE_HEADERS, subtitle_rows)
        written_subtitle_path = subtitle_path

    return SimpleTimelineSummary(
        timeline_csv=timeline_path,
        subtitles_csv=written_subtitle_path,
        mode="beginner",
        clip_count=len(timeline_rows),
        video_count=video_count,
        image_count=image_count,
        subtitle_count=len(subtitle_rows),
        total_duration=cursor,
        warnings=tuple(warnings),
    )


# 이름만 보고도 역할을 찾기 쉽도록 공개 별칭을 제공한다. 새 코드에서는
# build_simple_timeline을, 통합 코드에서는 adapt_simple_timeline을 써도 같다.
adapt_simple_timeline = build_simple_timeline
