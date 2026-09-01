# 릴리스 관리자 체크리스트

이 문서는 공개 직전의 보안·재현성·태그를 점검합니다. 처음 업로드한다면 [GitHub 업로드 가이드](01_GITHUB_PUBLISH.md)를 먼저 따르세요.

## GitHub ID의 범위

- 필요함: 코드를 자신의 GitHub 저장소에 업로드하는 배포자
- 필요 없음: Public 저장소를 clone하거나 ZIP으로 내려받는 사용자
- 필요 없음: 로컬 변환 도구를 실행하는 사용자

Colab을 제공할 때 배포자 ID는 저장소 URL을 설정하는 데 한 번 사용됩니다. 사용자가 입력하는 개인정보가 아닙니다.

## 1. 릴리스 값

이번 공개값을 한 곳에 적어 두고 문서·코드·태그를 맞춥니다.

| 항목 | 예시 |
|---|---|
| 저장소 | `csv-to-fcpxml-starter` |
| 릴리스 태그 | `v0.6.0` |
| Python 패키지 버전 | `0.6.0` |
| FCPXML 규격 | 코드의 현재 고정값 |

Colab을 제공할 때만 주소 설정 도구를 실행합니다.

```bash
python scripts/configure_github.py 내-GitHub-ID \
  --repo csv-to-fcpxml-starter \
  --ref v0.6.0
```

README 버튼, 노트북 `REPO_URL`, `REPO_REF`가 같은 저장소와 태그를 가리키는지 확인합니다. 사용자용 노트북은 계속 바뀌는 `main`보다 검증한 태그 또는 commit hash를 사용합니다.

## 2. 공개 제외 파일

```bash
git status --short
find . -type f -size +10M -not -path './.git/*' -print
```

다음 항목이 commit에 없어야 합니다.

- 실제 사용자 미디어·음악·폰트
- 개인정보·회사 자료·NDA 원본
- API 키, GitHub 토큰과 자격증명
- 사용자 기획표와 자막 전문
- `projects/`, `Generated/`, `.build_media/`, 결과 ZIP
- `.venv/`, 캐시와 임시 파일
- 실행 출력이 저장된 노트북 셀
- 특정 Mac의 `/Users/...` 절대경로

## 3. 자동 검사

새 가상환경에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
bash scripts/run_beginner_demo.sh
```

필수 확인:

- `.xlsx`와 UTF-8 `.csv` 입력
- 사진과 영상 혼합
- `portrait`, `landscape`, `both`
- 방향별 화면 맞춤 열과 적용 우선순위
- 세로·가로 결과 폴더 분리
- Title·clean FCPXML과 SRT
- 생성된 XML의 해상도·FPS 자동 검증
- `--preview-only` HTML의 예상 크롭·여백·자막 줄바꿈·안전영역
- 상대 미디어 경로와 `.build_media` 보존
- 오류 시 부분 성공을 정상 결과처럼 남기지 않음

## 4. Mac·Final Cut 실기 검사

자동 테스트는 Final Cut의 실제 렌더링을 대신하지 못합니다.

1. 세로 9:16 Title XML 가져오기
2. 가로 16:9 Title XML 가져오기
3. clean XML 가져오기
4. 영상 트림과 사진 길이 확인
5. `전체 보이기`의 여백 확인
6. `화면 채우기`의 크롭 확인
7. 방향별 자막 위치·줄바꿈·안전영역 확인
8. 원본 오디오 `사용`·`끄기` 확인
9. 기본 Share 결과에 Basic Title이 보이는지 확인
10. 프로젝트 폴더를 복사한 뒤 상대 경로가 유지되는지 확인

Release 설명에 실제 확인한 macOS와 Final Cut Pro 버전을 기록합니다.

## 5. 문서 점검

- README 첫 화면에서 Mac 로컬 실행이 기본으로 보임
- Colab은 설치 없는 선택 경로로 설명됨
- 일반 사용자에게 GitHub ID를 요구하지 않음
- `README.md`, `START_HERE.md`, `MAC.md`의 명령이 같음
- `.xlsx`, Numbers 내보내기와 UTF-8 CSV 설명이 일치함
- `--layout portrait|landscape|both`가 일관되게 쓰임
- 기존 `--portrait`, `--landscape`는 호환 별칭으로만 설명됨
- 결과 폴더와 실제 생성 이름이 일치함
- 다른 편집 프로그램과의 XML 호환을 보장하지 않음
- 모든 상대 Markdown 링크가 실제 파일을 가리킴
- placeholder와 이전 버전이 공개 화면에 남지 않음

확인 명령 예:

```bash
rg -n 'GITHUB_ID|YOUR_GITHUB|OWNER/REPOSITORY|v0\.[0-5]\.[0-9]+|--portrait|--landscape' \
  README.md START_HERE.md docs notebooks pyproject.toml
```

검색 결과는 무조건 0개여야 하는 것이 아닙니다. 배포자 예시·호환 옵션인지, 사용자에게 입력을 요구하는 잘못된 안내인지 직접 판단합니다.

## 6. 공개 Colab 검사 — 제공할 때만

시크릿 창에서 다음을 확인합니다.

- README 버튼이 검증한 태그의 노트북을 엶
- Starter ZIP, GitHub ID, 토큰을 사용자에게 요구하지 않음
- `timeline.xlsx` 또는 `.csv`와 미디어만 요구함
- `.numbers`는 Excel `.xlsx`로 내보내라고 안내함
- `portrait`, `landscape`, `both` 선택이 동작함
- 결과 ZIP에 원본 미디어와 실행 파일이 포함되지 않음
- 작업 후 런타임 삭제 안내가 보임
- Google Drive 마운트나 별도 업로드 서버를 사용하지 않음

## 7. 태그와 Release

검증한 commit에만 태그를 붙입니다.

```bash
git tag -a v0.6.0 -m "Mac-first portrait and landscape FCPXML release"
git push origin main
git push origin v0.6.0
```

공개한 태그는 옮기거나 재사용하지 않습니다. 수정은 새 patch 버전으로 냅니다.

Release에는 다음을 적습니다.

- 주요 기능과 입력 형식
- Mac 로컬 빠른 시작 링크
- 선택 Colab 링크
- 실제 검증 환경
- 알려진 제한과 다른 편집기 호환 범위
- 파일·미디어 저작권은 사용자 책임이라는 점

## 8. 공개 후 재현 확인

공개 저장소를 새 폴더에 clone한 뒤 같은 명령을 실행합니다.

```bash
git clone --branch v0.6.0 --depth 1 \
  https://github.com/OWNER/csv-to-fcpxml-starter.git release-check
cd release-check
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
bash scripts/run_beginner_demo.sh
```

마지막으로 Public 저장소가 로그인 없이 열리고 ZIP 다운로드가 가능한지 확인합니다.

## 9. 저장소 보호 권장사항

- 테스트 통과를 main 반영 조건으로 설정
- main force-push 금지
- 공개 Release tag 수정·재사용 금지
- 노트북·업로드·패키징 코드는 리뷰 필수
- 이슈에는 비식별 최소 재현만 요청
- 사용자 원본 업로드를 요구하지 않음

코드의 MIT License가 사용자 미디어·음악·폰트에 자동 적용되지는 않습니다. 예제 자산도 각각 공개 권한을 확인하세요.
