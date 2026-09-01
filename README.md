# 기획표 + 사진·영상 → Final Cut Pro 타임라인

Excel 또는 CSV 기획표에 장면 순서와 자막을 적으면, 사진·영상을 연결한 **편집 가능한 Final Cut Pro 초안 타임라인**을 만듭니다.

- 세로 9:16: Instagram Reels·YouTube Shorts용
- 가로 16:9: 일반 YouTube용
- 둘 다: 같은 편집안으로 세로·가로 프로젝트를 한 번에 생성
- 화면 자막을 적었을 때: Basic Title과 SRT 생성

> **권장 경로는 Mac 로컬 실행입니다.** 결과를 실제로 가져올 Final Cut Pro가 Mac 전용이고, 원본 미디어를 외부 실행 환경에 올리지 않아도 되기 때문입니다. 설치 없이 먼저 시험하고 싶을 때만 [Google Colab](notebooks/CSV_to_FCPXML_Colab.ipynb)을 선택하세요.

<!-- PUBLIC_COLAB_LINK_START -->
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Kongdataif/csv-to-fcpxml-starter/blob/v0.6.0/notebooks/CSV_to_FCPXML_Colab.ipynb)
<!-- PUBLIC_COLAB_LINK_END -->

## 준비물

- `timeline.xlsx` 또는 UTF-8 `timeline.csv`
- 기획표에 적은 사진·영상
- Python 3.10 이상과 FFmpeg가 설치된 Mac
- 결과를 가져올 Final Cut Pro

Numbers 사용자는 기획표를 `파일 > 다음으로 내보내기 > Excel`로 저장합니다. `.numbers` 파일 자체는 입력하지 않습니다.

입력 파일은 다음 규칙으로 고릅니다. `.xlsx`와 `.csv` 사이에는 자동 우선순위가 없습니다.

- `--timeline 파일명`을 쓰면 그 파일을 사용합니다.
- 옵션을 생략하면 프로젝트 폴더의 `timeline.xlsx` 또는 `timeline.csv` 한 개를 찾습니다. 둘 다 있으면 하나를 지우거나 `--timeline`으로 명시해야 합니다.
- 두 표준 이름이 없을 때만 프로젝트 폴더의 다른 `.xlsx`/`.csv`가 정확히 한 개이면 사용합니다. 후보가 여러 개면 자동으로 추측하지 않습니다.
- 별도 정밀 자막은 프로젝트 루트나 `Docs/`의 `subtitles.xlsx`/`subtitles.csv`를 사용합니다. 표준 이름이 없으면 `Docs/`의 유일한 `*대사표*.xlsx`/`.csv`도 찾습니다. 둘 다 있거나 같은 단계의 후보가 여러 개면 `--subtitles`로 하나를 명시합니다.
- 초보자 기획표의 `화면 자막` 열과 별도 자막표는 동시에 사용하지 않습니다. 별도 자막 자동 탐색을 끄려면 `--no-subtitles`를 사용합니다.

## Mac에서 빠르게 시작

공개 GitHub 저장소의 `Code > Download ZIP`으로 내려받아 압축을 풉니다. Git을 사용한다면 `Code > HTTPS`의 복사 버튼을 누른 직후 Mac Terminal에서 실행합니다.

```bash
git clone "$(pbpaste)"
cd csv-to-fcpxml-starter
```

공개 저장소를 받는 사용자는 **GitHub ID나 GitHub 계정이 필요하지 않습니다.** 계정은 이 코드를 자신의 저장소에 올리는 배포자에게만 필요합니다.

처음 한 번 설치합니다.

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

다음 구조로 내 프로젝트를 준비합니다.

```text
projects/my-video/
├─ timeline.xlsx          # 또는 timeline.csv
└─ Media/
   ├─ intro.mov
   ├─ drawing.png
   └─ outro.mp4
```

입력을 검사하고 세로·가로 미리보기를 확인한 뒤 XML을 만듭니다.

```bash
python make_xml.py projects/my-video --layout both --validate-only
python make_xml.py projects/my-video --layout both --preview-only
python make_xml.py projects/my-video --layout both
```

기본 미리보기는 `projects/my-video/Generated/preview/index.html`입니다. 브라우저에서 열어 예상 크롭·여백·자막 안전영역을 확인합니다.

한 방향만 만들려면 `both` 대신 `portrait` 또는 `landscape`를 사용합니다.

```bash
python make_xml.py projects/my-video --layout portrait
python make_xml.py projects/my-video --layout landscape
```

기존 `--portrait`, `--landscape` 옵션도 호환을 위해 사용할 수 있지만 이전의 평면 `Generated/` 구조를 유지합니다. 새 프로젝트는 방향별 폴더가 생기는 `--layout`을 사용하세요.

## 기획표 기본 6열

| 열 | 무엇을 적나요? | 빈칸이면 |
|---|---|---|
| `파일` | `Media` 안의 실제 파일명 | 필수 |
| `영상 원본 시작` | 영상에서 사용할 구간 시작 | 시작·끝 모두 빈칸이면 전체 사용 |
| `영상 원본 끝` | 영상에서 사용할 구간 끝 | 시작·끝 모두 빈칸이면 전체 사용 |
| `사진 표시 시간(초)` | 사진을 보여줄 시간 | 3초 |
| `화면 자막` | 장면 동안 보일 문장 | 자막 없음 |
| `소리` | 영상은 `사용` 또는 `끄기` | 원본 소리 사용 |

```csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
intro.mov,00:00:01.000,00:00:04.000,,첫 장면,사용
drawing.png,,,3,아이패드로 그린 그림,
outro.mp4,,,,다음 편에 계속,끄기
```

파일명은 확장자와 대소문자까지 실제 파일과 같아야 합니다. 처음에는 [Excel·Numbers용 양식](templates/simple_timeline.xlsx)을 복사해 사용하세요.

GitHub에서 바로 볼 수 있는 예제: [기본 6열 CSV](examples/quick_start/timeline.csv) · [세로·가로 CSV](examples/multi_format/timeline.csv). Excel로 바로 작성하려면 [세로·가로 Excel 양식](templates/multi_format_timeline.xlsx)을 사용하세요.

## 결과와 Final Cut 가져오기

`--layout both`의 결과는 서로 덮어쓰지 않도록 나뉩니다.

```text
projects/my-video/Generated/
├─ preview/index.html
├─ vertical_9x16/
│  ├─ my-video_vertical_9x16_with_titles.fcpxml
│  └─ my-video_vertical_9x16_clean.fcpxml
└─ horizontal_16x9/
   ├─ my-video_horizontal_16x9_with_titles.fcpxml
   └─ my-video_horizontal_16x9_clean.fcpxml
```

1. Final Cut Pro에서 테스트 Library를 엽니다.
2. `File(파일) > Import(가져오기) > XML`을 선택합니다.
3. 자막이 있으면 `*_with_titles.fcpxml`, 없으면 `*_clean.fcpxml`을 선택합니다.
4. 장면 순서, 잘림·여백, 자막 위치와 소리를 확인합니다.
5. 편집을 마친 뒤 `File(파일) > Share(공유)`로 영상을 내보냅니다.

화면 자막은 Basic Title이므로 Caption 번인 설정 없이 일반 영상 내보내기에 표시됩니다.

## Colab은 선택 경로

Python과 FFmpeg를 설치하지 않고 짧은 샘플로 먼저 시험하려면 [초보자 Colab 안내](docs/02_BEGINNER_COLAB.md)를 사용하세요. 기획표와 미디어가 Colab의 임시 실행 환경에 업로드되므로 기밀·NDA·대용량 원본에는 Mac 로컬 실행을 권장합니다.

## 다른 편집 프로그램에서도 같은 XML을 쓰나요?

항상 그렇지는 않습니다. 이 도구가 만드는 `.fcpxml`은 **Final Cut Pro용 FCPXML**입니다. 다른 편집기는 서로 다른 XML 규격이나 제한된 가져오기 기능을 사용할 수 있으므로, 파일 확장자가 XML이라고 해서 동일하게 열리는 것은 아닙니다. 자세한 범위는 [편집 프로그램 호환성](docs/EDITOR_COMPATIBILITY.md)을 확인하세요.

## 문서

- 개발·배포·사용 전체 순서: [START HERE](START_HERE.md)
- 처음부터 Mac에서 실행: [Mac·VS Code 가이드](docs/MAC.md)
- 기획표 작성: [사용자 가이드](docs/USER_GUIDE.md)
- GitHub에 공개: [GitHub 업로드 가이드](docs/01_GITHUB_PUBLISH.md)
- 오류 해결: [문제 해결](docs/TROUBLESHOOTING.md)
- 고급 타임라인·BGM·dB: [고급 입력 형식](docs/INPUT_FORMAT.md)

## 라이선스

코드는 MIT License입니다. 사진·영상·음악·폰트의 사용 및 배포 권한은 사용자가 직접 확인해야 합니다.
