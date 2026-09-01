# START HERE — 실행, 공개, 사용자 전달

이 프로젝트는 **Mac에서 검증 → GitHub 공개 → 사용자가 Mac 또는 Colab에서 실행**하는 순서로 운영합니다.

| 단계 | 대상 | 할 일 | 완료 기준 |
|---|---|---|---|
| 0 | 개발자 | Mac 가상환경에서 테스트 실행 | 세로·가로 FCPXML 생성 및 Final Cut 가져오기 성공 |
| 1 | 배포자 | 검증한 코드를 GitHub Public 저장소에 공개 | 새 폴더에서 다시 내려받아 동일하게 실행 |
| 2 | 일반 사용자 | 기획표와 미디어로 초안 생성 | 원하는 비율의 XML을 Final Cut에서 확인 |

## 먼저 선택하세요

### Mac 로컬 — 기본 권장

- Final Cut Pro로 바로 가져올 수 있음
- 원본 사진·영상이 Mac 밖으로 나가지 않음
- 큰 영상과 반복 작업에 적합

[Mac·VS Code 전체 가이드](docs/MAC.md)

### Google Colab — 선택

- Python 설치 없이 브라우저에서 시험 가능
- 입력 파일이 Colab 임시 환경에 업로드됨
- 짧고 민감하지 않은 샘플에 적합

[초보자 Colab 가이드](docs/02_BEGINNER_COLAB.md)

## 0. 개발자가 Mac에서 먼저 확인

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

그다음 합성 미디어를 사용하는 초보자 데모로 세로와 가로를 함께 만듭니다.

```bash
bash scripts/run_beginner_demo.sh
```

두 결과의 해상도·FPS 검증이 통과하고 Final Cut에서 가져와지는지 확인합니다. 자세한 순서는 [Mac 검증 절차](docs/MAC.md)를 따릅니다.

## 1. GitHub에 공개

1. GitHub에서 비어 있는 Public 저장소를 만듭니다.
2. 현재 폴더를 Git 저장소에 연결해 올립니다.
3. 비밀정보와 실제 사용자 미디어가 포함되지 않았는지 확인합니다.
4. GitHub의 새 Clone 또는 Download ZIP으로 다시 받습니다.
5. Mac에서 설치·검사·생성을 다시 실행합니다.
6. 검증한 commit에 Release를 만듭니다.

GitHub ID는 이 단계의 **업로드 담당자**에게만 필요합니다. 공개 저장소를 clone하거나 ZIP으로 받는 일반 사용자는 GitHub ID를 입력하거나 계정을 만들 필요가 없습니다.

[GitHub 공개 상세 가이드](docs/01_GITHUB_PUBLISH.md)

## 2. 초보 사용자가 실행

초보 사용자에게는 아래 두 문서 중 하나만 전달하면 됩니다.

- Mac에서 실행: [Mac·VS Code 가이드](docs/MAC.md)
- 설치 없이 시험: [Colab 사용자 가이드](docs/02_BEGINNER_COLAB.md)

사용자 입력은 다음뿐입니다.

```text
my-video/
├─ timeline.xlsx 또는 timeline.csv
└─ Media/
   └─ 기획표에 적은 사진·영상
```

세로·가로를 함께 만들 때:

```bash
python make_xml.py projects/my-video --layout both
```

Final Cut에서는 각 결과 폴더의 `*_with_titles.fcpxml`을 `File > Import > XML`로 가져옵니다.

## 관련 문서

- 기획표와 선택 열: [사용자 가이드](docs/USER_GUIDE.md)
- 편집기별 XML 차이: [편집 프로그램 호환성](docs/EDITOR_COMPATIBILITY.md)
- 릴리스 보안 점검: [관리자 체크리스트](docs/PUBLISHING.md)
- 오류 해결: [문제 해결](docs/TROUBLESHOOTING.md)
