"""Testable Colab upload/result guards. Does not import google.colab."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Mapping

from run import (HEADERS, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, UserError, convert_xlsx,
                 digest, filename, invalidate_result, media_index, read_timeline,
                 verified_result, write_json)


def new_session(root: Path) -> Path:
    project = root / uuid.uuid4().hex / "my-video"
    project.mkdir(parents=True)
    write_json(project / ".uploads.json", {"plan": None, "media": None})
    invalidate_result(project, "새 세션입니다. 기획표와 미디어를 업로드하세요.")
    return project


def receipt(project: Path) -> dict:
    try:
        return json.loads((project / ".uploads.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"plan": None, "media": None}


def begin_upload(project: Path, kind: str) -> None:
    state = receipt(project)
    if kind not in {"plan", "media"}:
        raise ValueError(kind)
    state[kind] = None
    if kind == "plan":
        state["media"] = None
    write_json(project / ".uploads.json", state)
    invalidate_result(project, "입력을 다시 선택했습니다. 업로드와 변환을 완료하세요.")


def normalized_upload(uploaded: Mapping[str, bytes]) -> dict[str, bytes]:
    result = {}
    for name, data in uploaded.items():
        key = filename(name)
        if key in result:
            raise UserError(f"중복 파일명입니다: {key}")
        if not data:
            raise UserError(f"빈 파일입니다: {key}")
        result[key] = bytes(data)
    return result


def save_plan(project: Path, uploaded: Mapping[str, bytes]) -> list[dict[str, str]]:
    begin_upload(project, "plan")
    items = normalized_upload(uploaded)
    if len(items) != 1:
        raise UserError("CSV 또는 XLSX 기획표를 정확히 한 개 선택하세요.")
    name, data = next(iter(items.items()))
    suffix = Path(name).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise UserError("기획표는 CSV/XLSX만 지원합니다. Numbers는 Excel로 내보내세요.")
    with tempfile.TemporaryDirectory(prefix=".plan-", dir=project) as temporary:
        source = Path(temporary) / ("timeline" + suffix)
        source.write_bytes(data)
        csv_path = convert_xlsx(source, Path(temporary) / "preview.csv") if suffix == ".xlsx" else source
        rows = read_timeline(csv_path)
        expected = sorted({filename(row["파일"]) for row in rows})
        if any(Path(n).suffix.lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS for n in expected):
            raise UserError("기획표에 지원하지 않는 미디어 형식이 있습니다.")
        target = project / source.name
        os.replace(source, target)
    other = project / ("timeline.xlsx" if suffix == ".csv" else "timeline.csv")
    other.unlink(missing_ok=True)
    write_json(project / ".uploads.json", {"plan": {"name": target.name, "sha256": digest(target), "expected": expected}, "media": None})
    return rows


def require_plan(project: Path) -> dict:
    state = receipt(project)
    plan = state.get("plan")
    try:
        if not plan or digest(project / plan["name"]) != plan["sha256"]:
            raise UserError("2번에서 기획표 업로드를 완료하세요. 변경했다면 미디어도 다시 선택하세요.")
    except OSError as exc:
        raise UserError("기획표가 없습니다. 2번을 다시 실행하세요.") from exc
    return state


def save_media(project: Path, uploaded: Mapping[str, bytes]) -> list[str]:
    begin_upload(project, "media")
    state = require_plan(project)
    items = normalized_upload(uploaded)
    expected = set(state["plan"]["expected"])
    missing = expected - items.keys()
    if missing:
        raise UserError("업로드하지 않은 미디어: " + ", ".join(sorted(missing)))
    invalid = [n for n in items if Path(n).suffix.lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS]
    if invalid:
        raise UserError("사진·영상만 선택하세요: " + ", ".join(invalid))
    # Replace the session's media set; unreferenced uploads and old sessions are never packaged.
    stage = Path(tempfile.mkdtemp(prefix=".media-", dir=project))
    backup = project / (".previous-media-" + uuid.uuid4().hex)
    target = project / "Media"
    try:
        for name in expected:
            (stage / name).write_bytes(items[name])
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except OSError:
            if backup.exists():
                os.replace(backup, target)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if backup.exists():
            shutil.rmtree(backup)
    state["media"] = {n: digest(target / n) for n in sorted(expected)}
    write_json(project / ".uploads.json", state)
    return sorted(set(items) - expected)


def require_uploads(project: Path) -> None:
    state = require_plan(project)
    media = state.get("media")
    if not media or set(media) != set(state["plan"]["expected"]):
        raise UserError("3번에서 기획표의 사진·영상 전체 업로드를 완료하세요.")
    try:
        if any(digest(project / "Media" / n) != sha for n, sha in media.items()):
            raise UserError("업로드 후 미디어가 변경되었습니다. 3번부터 다시 실행하세요.")
    except OSError as exc:
        raise UserError("미디어가 누락되었습니다. 3번부터 다시 실행하세요.") from exc


def make_result_archive(project: Path, destination: Path) -> Path:
    """Package only a verified build. Never silently archive an earlier output."""
    report = verified_result(project)
    names = sorted(report["files"])
    report_name = "output/build_report.json"
    expected_hashes = {**report["files"], report_name: digest(project / report_name)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for name in [*names, report_name]:
                h = hashlib.sha256()
                with (project / name).open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        h.update(block)
                        target.write(block)
                if h.hexdigest() != expected_hashes[name]:
                    raise UserError(f"압축 중 파일이 변경되었습니다: {name}. 다시 변환하세요.")
        # Catch a new failed build or input selection that happened during packaging.
        if verified_result(project)["build_id"] != report["build_id"]:
            raise UserError("압축 중 새 변환이 시작되었습니다. 다시 다운로드하세요.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
