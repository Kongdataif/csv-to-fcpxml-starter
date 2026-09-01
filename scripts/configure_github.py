#!/usr/bin/env python3
"""공개 저장소 주소를 README와 Colab 노트북에 한 번에 설정한다.

일반 사용자는 GitHub ID를 입력하지 않는다. 이 파일은 저장소를 처음
공개하는 배포자가 한 번 실행하며, 다음 두 곳을 같은 값으로 맞춘다.

1. README 첫 화면의 ``Open in Colab`` 버튼
2. Colab 노트북이 코드를 내려받을 ``REPO_URL``과 고정 ``REPO_REF``

외부 패키지를 사용하지 않고, 파일 전체가 준비된 뒤 같은 폴더에서 원자적으로
교체한다. 중간에 오류가 나면 기존 README와 노트북은 그대로 남는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "CSV_to_FCPXML_Colab.ipynb"
COLAB_START = "<!-- PUBLIC_COLAB_LINK_START -->"
COLAB_END = "<!-- PUBLIC_COLAB_LINK_END -->"


def validate_slug(value: str, *, label: str, allow_slash: bool = False) -> str:
    """주소에 안전한 GitHub 소유자·저장소·ref 문자열만 받는다."""

    value = value.strip()
    pattern = r"[A-Za-z0-9][A-Za-z0-9._/-]*" if allow_slash else r"[A-Za-z0-9][A-Za-z0-9._-]*"
    if not re.fullmatch(pattern, value) or ".." in value or value.endswith((".", "/")):
        raise ValueError(f"{label} 형식이 올바르지 않습니다: {value!r}")
    return value


def replace_colab_block(readme: str, *, owner: str, repository: str, ref: str) -> str:
    """마커 사이만 바꿔 문서의 나머지 내용을 보존한다."""

    if readme.count(COLAB_START) != 1 or readme.count(COLAB_END) != 1:
        raise ValueError("README의 Colab 링크 마커를 정확히 한 쌍 찾을 수 없습니다.")
    start = readme.index(COLAB_START)
    end = readme.index(COLAB_END, start) + len(COLAB_END)
    notebook_url = (
        "https://colab.research.google.com/github/"
        f"{owner}/{repository}/blob/{ref}/notebooks/CSV_to_FCPXML_Colab.ipynb"
    )
    block = (
        f"{COLAB_START}\n"
        f"[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)]({notebook_url})\n"
        f"{COLAB_END}"
    )
    return readme[:start] + block + readme[end:]


def update_notebook(data: dict[str, object], *, repository_url: str, ref: str) -> None:
    """코드 셀의 설정 두 줄을 찾아 값만 교체한다."""

    replacements = {
        "REPO_URL": f'REPO_URL = "{repository_url}"\n',
        "REPO_REF": f'REPO_REF = "{ref}"\n',
    }
    counts = {name: 0 for name in replacements}
    cells = data.get("cells")
    if not isinstance(cells, list):
        raise ValueError("노트북의 cells 목록을 찾을 수 없습니다.")

    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source")
        if not isinstance(source, list):
            continue
        for index, line in enumerate(source):
            if not isinstance(line, str):
                continue
            for name, replacement in replacements.items():
                if line.startswith(f"{name} ="):
                    source[index] = replacement
                    counts[name] += 1

    missing = [name for name, count in counts.items() if count != 1]
    if missing:
        raise ValueError(f"노트북 설정 줄을 정확히 하나씩 찾지 못했습니다: {', '.join(missing)}")


def atomic_write(path: Path, text: str) -> None:
    """같은 폴더의 임시 파일을 완성한 뒤 최종 파일과 교체한다."""

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def configure_repository(root: Path, *, owner: str, repository: str, ref: str) -> tuple[str, str]:
    """지정한 저장소 루트의 README와 노트북을 함께 설정한다."""

    owner = validate_slug(owner, label="GitHub ID")
    repository = validate_slug(repository, label="저장소 이름")
    ref = validate_slug(ref, label="릴리스 ref", allow_slash=True)
    readme_path = root / "README.md"
    notebook_path = root / "notebooks" / "CSV_to_FCPXML_Colab.ipynb"
    repository_url = f"https://github.com/{owner}/{repository}.git"

    original_readme = readme_path.read_text(encoding="utf-8")
    notebook_data = json.loads(notebook_path.read_text(encoding="utf-8"))
    updated_readme = replace_colab_block(
        original_readme, owner=owner, repository=repository, ref=ref
    )
    update_notebook(notebook_data, repository_url=repository_url, ref=ref)
    updated_notebook = json.dumps(notebook_data, ensure_ascii=False, indent=1) + "\n"

    # 두 결과를 모두 메모리에서 검증한 뒤 쓰므로 단순 입력 오류가 반쪽 설정을
    # 만들지 않는다. 디스크 장애 시에는 Git 또는 원본 ZIP으로 복구할 수 있다.
    atomic_write(readme_path, updated_readme)
    atomic_write(notebook_path, updated_notebook)
    return repository_url, ref


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="README의 Colab 버튼과 노트북 GitHub 주소를 한 번에 설정합니다."
    )
    parser.add_argument("github_id", help="저장소를 공개할 GitHub 사용자명 또는 조직명")
    parser.add_argument("--repo", default="csv-to-fcpxml-starter", help="저장소 이름")
    parser.add_argument("--ref", default="v0.6.0", help="사용자에게 제공할 릴리스 태그")
    args = parser.parse_args(argv)

    try:
        repository_url, ref = configure_repository(
            REPO_ROOT,
            owner=args.github_id,
            repository=args.repo,
            ref=args.ref,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"오류: {exc}\n")

    print("GitHub 공개 주소 설정 완료")
    print(f"- 저장소: {repository_url.removesuffix('.git')}")
    print(f"- Colab 코드 기준: {ref}")
    print("README와 노트북을 확인한 뒤 GitHub에 업로드하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
