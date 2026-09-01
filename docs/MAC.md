# Mac·VS Code 초보자 가이드

이 방법을 기본으로 권장합니다. 기획표와 원본 사진·영상이 Mac 안에서 처리되고, 만든 XML을 바로 Final Cut Pro로 가져올 수 있습니다.

처음 한 번은 개발 도구를 설치해야 하지만, 그다음부터는 기획표와 미디어를 바꾸고 같은 명령을 다시 실행하면 됩니다.

## 전체 순서

1. 저장소 받기
2. Python과 FFmpeg 준비
3. 가상환경 만들기
4. `timeline.xlsx`/`timeline.csv`와 `Media` 준비
5. 입력 검사
6. 세로·가로 XML 생성
7. Final Cut Pro로 가져오기

## 1. 필요한 것

- Mac
- Final Cut Pro
- Python 3.10 이상
- FFmpeg와 FFprobe
- 이 저장소
- 내 기획표와 사진·영상

GitHub의 Public 저장소를 내려받는 데 GitHub ID나 GitHub 계정은 필요하지 않습니다.

## 2. Terminal 열기

1. `Command + Space`를 누릅니다.
2. `Terminal` 또는 `터미널`을 검색합니다.
3. Return을 누릅니다.

Python을 확인합니다.

```bash
python3 --version
```

`Python 3.10` 이상이 표시되어야 합니다. 명령을 찾지 못하거나 버전이 낮으면 [Python 공식 macOS 설치 페이지](https://www.python.org/downloads/macos/)에서 설치합니다.

## 3. 저장소 받기

### 방법 A — ZIP으로 받기

Git을 처음 사용한다면 이 방법이 가장 단순합니다.

1. GitHub 저장소에서 `Code > Download ZIP`을 누릅니다.
2. Finder의 `Downloads`에서 ZIP을 더블클릭합니다.
3. 풀린 `csv-to-fcpxml-starter` 폴더를 원하는 위치로 옮깁니다.
4. Terminal에 `cd`와 공백 하나를 입력합니다.
5. 그 폴더를 Terminal 창에 끌어다 놓고 Return을 누릅니다.

예:

```bash
cd "/Users/내이름/Documents/csv-to-fcpxml-starter"
```

### 방법 B — 공개 저장소 clone

Git을 사용할 수 있다면 GitHub의 `Code > HTTPS` 주소를 복사합니다.

```bash
git clone "$(pbpaste)"
cd csv-to-fcpxml-starter
```

`pbpaste`는 방금 복사한 HTTPS 주소를 Terminal 명령에 붙여 넣는 Mac 명령입니다.

공개 저장소 clone은 로그인 없이 가능합니다. 저장소에 코드를 다시 올릴 사람만 GitHub 계정이 필요합니다.

## 4. VS Code에서 폴더 열기

1. VS Code를 엽니다.
2. `File > Open Folder`를 선택합니다.
3. `csv-to-fcpxml-starter` 폴더를 엽니다.
4. 상단 메뉴에서 `Terminal > New Terminal`을 선택합니다.

아래 명령은 모두 VS Code 하단 Terminal에서도 같습니다. Terminal 경로 끝에 `csv-to-fcpxml-starter`가 보이는지 확인하세요.

## 5. FFmpeg 설치

Homebrew가 이미 있다면 다음을 실행합니다.

```bash
brew install ffmpeg
ffmpeg -version
ffprobe -version
```

`brew: command not found`가 나오면 [Homebrew 공식 사이트](https://brew.sh/)의 설치 명령을 사용합니다. 설치 과정에서 Mac 비밀번호를 입력할 때 글자나 점이 보이지 않는 것은 정상입니다.

FFmpeg와 FFprobe는 다음을 위해 필요합니다.

- 실제 사진인지 영상인지 확인
- 영상 길이·해상도·FPS·오디오 검사
- 사진을 Final Cut용 편집 캐시로 준비
- 세로·가로 결과의 기술 정보 검증

## 6. Python 가상환경 만들기

저장소 폴더에서 다음을 순서대로 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Terminal 줄 앞에 `(.venv)`가 보이면 활성화된 것입니다.

이후 VS Code를 새로 열 때마다 먼저 다음 한 줄을 실행합니다.

```bash
source .venv/bin/activate
```

작업을 끝낼 때는 다음을 실행할 수 있습니다.

```bash
deactivate
```

## 7. 설치 상태 먼저 검사

내 파일을 넣기 전에 자동 테스트를 실행하면 설치 오류와 기획표 오류를 구분하기 쉽습니다.

```bash
python -m unittest discover -s tests -v
```

그다음 합성 미디어를 만드는 초보자 데모를 검사합니다.

```bash
bash scripts/run_beginner_demo.sh
```

스크립트가 세로와 가로 XML 생성·해상도 검증까지 통과하면 기본 설치가 완료된 것입니다. `examples/quick_start`에는 배포용 실제 미디어가 없으므로 그 폴더를 `make_xml.py`로 직접 실행하지 않습니다.

### VS Code에서 명령 복사 없이 실행하기

`.venv`를 한 번 만든 뒤에는 VS Code의 작업 메뉴를 사용할 수 있습니다.

1. `Command + Shift + P`로 Command Palette를 엽니다.
2. `Tasks: Run Task`를 선택합니다.
3. `1. 세로·가로 입력 검사` → `2. 세로·가로 미리보기` → `3. 세로·가로 XML 만들기 (추천)` 순으로 실행합니다.
4. 물어보는 프로젝트 경로에 `projects/my-video`처럼 입력합니다.

세로만 만들어 Final Cut으로 보내려면 5번, 가로는 7번 작업을 선택합니다. 작업이 실행되지 않으면 먼저 이 문서의 가상환경 설치와 설치 검사를 완료했는지 확인하세요.

## 8. 내 프로젝트 폴더 만들기

저장소 안에 다음 구조를 만듭니다. Finder나 VS Code의 새 폴더 기능을 사용해도 됩니다.

```text
csv-to-fcpxml-starter/
└─ projects/
   └─ my-video/
      ├─ timeline.xlsx       # 또는 timeline.csv
      └─ Media/
         ├─ intro.mov
         ├─ drawing.png
         └─ outro.mp4
```

처음에는 [기본 Excel 양식](../templates/simple_timeline.xlsx)을 복사해 `timeline.xlsx`로 사용하세요.

방향별 선택 열이 필요한 경우에는 [세로·가로 Excel 양식](../templates/multi_format_timeline.xlsx)을 복사합니다. GitHub에서 내용을 먼저 확인하려면 [같은 내용의 CSV 예제](../examples/multi_format/timeline.csv)를 참고하세요.

- Excel: `.xlsx` 그대로 저장
- Numbers: `파일 > 다음으로 내보내기 > Excel`로 `.xlsx` 저장
- CSV: `CSV UTF-8`로 저장
- `.numbers` 파일 자체는 입력하지 않음

같은 폴더에 `timeline.xlsx`와 `timeline.csv`를 둘 다 두면 어느 파일이 최신인지 도구가 추측하지 않습니다. 하나만 남기거나 다음처럼 지정합니다.

```bash
python make_xml.py projects/my-video --timeline timeline.xlsx --layout both
```

정확한 타임라인 선택 규칙은 다음과 같습니다. `.xlsx`와 `.csv` 사이에는 자동 우선순위가 없습니다.

1. `--timeline`을 쓰면 지정한 프로젝트 내부 파일을 사용합니다.
2. 생략하면 프로젝트 폴더의 `timeline.xlsx` 또는 `timeline.csv`를 찾습니다.
3. 두 표준 이름이 모두 없을 때만, 프로젝트 폴더의 다른 `.xlsx`/`.csv`가 정확히 한 개이면 그 파일을 사용합니다.
4. 같은 단계의 후보가 여러 개이면 중단하므로 파일을 지우지 않아도 `--timeline`으로 명시할 수 있습니다.

한 장면 안에서 자막이 여러 번 바뀌는 정밀 작업에는 별도 자막표를 둘 수 있습니다.

```text
projects/my-video/
├─ timeline.xlsx
├─ subtitles.xlsx          # 또는 subtitles.csv
├─ Media/
└─ Docs/
   └─ 촬영본_대사표.xlsx    # 표준 subtitles 파일이 없을 때 쓸 수 있는 대안
```

- `--subtitles 파일명`을 쓰면 그 파일을 사용합니다.
- 생략하면 프로젝트 루트와 `Docs/`에서 `subtitles.xlsx`/`subtitles.csv`를 찾고, 없으면 `Docs/`의 유일한 `*대사표*.xlsx`/`.csv`를 찾습니다.
- 루트와 `Docs/`, XLSX와 CSV를 통틀어 같은 단계의 후보가 여러 개면 우선순위를 정하지 않고 오류를 냅니다. `--subtitles Docs/파일명.xlsx`처럼 하나를 지정합니다.
- 별도 자막표를 쓰려면 타임라인의 `화면 자막` 열을 모두 비웁니다. 두 입력에 자막이 동시에 있으면 중단합니다.
- 별도 자막 자동 탐색을 끄려면 `--no-subtitles`를 사용합니다. `--no-subtitles`와 `--subtitles`는 함께 쓸 수 없습니다.
- 자막표도 `.numbers`를 직접 읽지 않습니다. Numbers에서 `파일 > 다음으로 내보내기 > Excel`로 `.xlsx`를 만든 뒤 사용합니다.

## 9. 기획표 작성

기본 열은 여섯 개입니다.

| 열 | 입력 |
|---|---|
| `파일` | `Media` 안의 실제 파일명 |
| `영상 원본 시작` | 영상에서 자르기 시작할 시간 |
| `영상 원본 끝` | 영상에서 자르기를 끝낼 시간 |
| `사진 표시 시간(초)` | 사진을 몇 초 보여줄지 |
| `화면 자막` | 장면 동안 표시할 Basic Title 문구 |
| `소리` | 영상은 `사용` 또는 `끄기` |

예:

```csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
intro.mov,00:00:01.000,00:00:04.000,,처음 Mac을 켰다,사용
drawing.png,,,3,아이패드로 그린 그림,
outro.mp4,,,,다음 편에 계속,끄기
```

중요한 규칙:

- 행 순서가 영상 장면 순서입니다.
- 파일명은 확장자와 대소문자까지 `Media`의 실제 파일과 같아야 합니다.
- 영상 전체를 쓰려면 원본 시작·끝을 모두 비웁니다.
- 사진 행에는 영상 원본 시작·끝을 비웁니다.
- 사진 표시 시간이 비면 기본 3초입니다.
- `화면 자막`은 별도 Caption이 아니라 일반 Basic Title로 생성됩니다.

## 10. 세로·가로 화면 맞춤

방향 선택은 명령에서 한 번만 합니다. 모든 행에 플랫폼 이름을 반복해서 쓰지 않습니다.

| 실행값 | 결과 | 주 용도 |
|---|---|---|
| `portrait` | 1080×1920, 9:16 | Reels·Shorts |
| `landscape` | 1920×1080, 16:9 | 일반 YouTube |
| `both` | 위 두 결과 모두 | 같은 편집안 동시 제작 |

대부분은 기획표 기본 6열만으로 시작해도 됩니다. 특정 장면의 배치가 중요할 때만 선택 열을 추가합니다.

| 선택 열 | 허용값 | 적용 범위 |
|---|---|---|
| `화면 맞춤` | `전체 보이기`, `화면 채우기` | 두 방향 공통 |
| `세로 화면 맞춤` | `전체 보이기`, `화면 채우기` | 세로 결과만 덮어씀 |
| `가로 화면 맞춤` | `전체 보이기`, `화면 채우기` | 가로 결과만 덮어씀 |

- `전체 보이기`: 원본 전체를 보존하지만 비율이 다르면 여백이 생길 수 있습니다.
- `화면 채우기`: 프레임을 채우지만 가장자리가 잘릴 수 있습니다.
- 방향별 열이 비어 있으면 공통 `화면 맞춤`을 사용합니다.
- 공통 열도 비어 있으면 안전한 기본값을 사용합니다.

세로·가로를 함께 만들 때 `--preview-only`로 원본 비율, 적용 방식, 예상 크롭·여백과 자막 줄바꿈을 먼저 확인할 수 있습니다. 자동 결과는 초안이므로 얼굴·제품·글자가 잘리는 장면은 Final Cut에서 최종 조정하세요.

## 11. XML을 만들기 전에 검사와 미리보기

### 입력 구조 검사

```bash
python make_xml.py projects/my-video --layout both --validate-only
```

이 명령은 결과 XML을 만들지 않고 다음을 확인합니다.

- 기획표 열과 값
- 미디어 파일명과 실제 존재 여부
- 사진·영상 종류
- 영상 길이와 원본 트림 범위
- 세로·가로 화면 맞춤
- 결과 해상도와 FPS 설정

`오류`가 나오면 결과를 만들지 않습니다. 표시된 행 번호를 기획표에서 고친 뒤 같은 명령을 다시 실행합니다. `경고`는 생성할 수 있지만 Final Cut에서 확인해야 하는 항목입니다.

### 세로·가로 화면 미리보기

구조 검사가 통과하면 다음을 실행합니다.

```bash
python make_xml.py projects/my-video --layout both --preview-only
```

명령이 안내한 HTML을 브라우저로 엽니다. 기본 경로는 `projects/my-video/Generated/preview/index.html`입니다. 다음을 방향별로 비교할 수 있습니다.

- 대표 썸네일
- `전체 보이기`의 예상 여백
- `화면 채우기`의 예상 크롭 영역
- 자막 줄바꿈과 안전영역
- 원본·결과 화면비

미리보기는 최종 XML을 만들기 전 검토 자료입니다. Final Cut의 정확한 폰트 렌더링과 사람이 화면 어디에 있는지는 최종 프로젝트에서도 확인하세요.

## 12. XML 만들기

### 세로와 가로를 모두 만들기 — 권장

```bash
python make_xml.py projects/my-video --layout both
```

### 세로만 만들기

```bash
python make_xml.py projects/my-video --layout portrait
```

### 가로만 만들기

```bash
python make_xml.py projects/my-video --layout landscape
```

이전 명령 형식을 사용하던 프로젝트를 위해 아래 별칭도 계속 지원합니다.

```bash
python make_xml.py projects/my-video --portrait
python make_xml.py projects/my-video --landscape
```

호환 별칭은 이전 버전과 같이 `Generated/` 바로 아래에 결과를 만듭니다. 방향별 폴더와 파일명이 필요한 새 작업에는 `--layout`을 사용하세요.

다른 FPS가 필요하면 명시합니다.

```bash
python make_xml.py projects/my-video --layout both --fps 29.97
```

## 13. 결과 폴더

`both`를 사용하면 두 방향이 별도 폴더에 생성되어 서로 덮어쓰지 않습니다.

```text
projects/my-video/
├─ timeline.xlsx
├─ Media/
└─ Generated/
   ├─ preview/
   │  └─ index.html
   ├─ vertical_9x16/
   │  ├─ my-video_vertical_9x16_clean.fcpxml
   │  ├─ my-video_vertical_9x16_with_titles.fcpxml
   │  ├─ my-video_vertical_9x16.srt
   │  ├─ build_report.txt
   │  └─ .build_media/
   └─ horizontal_16x9/
      ├─ my-video_horizontal_16x9_clean.fcpxml
      ├─ my-video_horizontal_16x9_with_titles.fcpxml
      ├─ my-video_horizontal_16x9.srt
      ├─ build_report.txt
      └─ .build_media/
```

| 결과 | 의미 |
|---|---|
| `preview/index.html` | 생성 전 세로·가로 배치 검토용 HTML |
| `*_with_titles.fcpxml` | 화면 자막이 있을 때 생성되는 Basic Title 추천 프로젝트 |
| `*_clean.fcpxml` | 화면 자막이 없는 프로젝트 |
| `*.srt` | 플랫폼에 별도로 올릴 수 있는 자막 파일 |
| `build_report.txt` | 입력·경고·해상도·FPS·생성 결과 |
| `.build_media` | 사진용 편집 캐시; 이동하거나 삭제하지 않음 |

생성 후 XML 내부의 프로젝트 해상도와 FPS를 자동 검증합니다. 검증에 실패하면 성공 결과처럼 안내하지 않습니다.

## 14. Final Cut Pro로 가져오기

처음에는 기존 작업과 분리된 테스트 Library에서 확인하세요.

1. Final Cut Pro를 엽니다.
2. 가져올 Library와 Event를 선택합니다.
3. `File(파일) > Import(가져오기) > XML`을 선택합니다.
4. 세로 결과는 `vertical_9x16`의 `*_with_titles.fcpxml`을 선택합니다. 화면 자막이 없다면 `*_clean.fcpxml`을 선택합니다.
5. 가로 결과도 `horizontal_16x9`에서 같은 기준으로 선택합니다.
6. Final Cut의 가져오기 화면에서 대상 Event를 확인합니다.
7. 두 프로젝트의 장면 순서, 트림, 소리, 자막과 화면 배치를 재생해 봅니다.

생성 직후 Final Cut으로 자동 전달하려면 `--open`을 붙입니다. `both`에서는 세로와 가로 XML을 차례로 전달합니다.

```bash
python make_xml.py projects/my-video --layout both --open
```

자동 전달이 실패하거나 대상 Library/Event를 더 명확히 고르고 싶다면 Final Cut에서 `File(파일) > Import(가져오기) > XML`을 선택하고 두 방향의 XML을 각각 가져옵니다.

## 15. Final Cut에서 반드시 확인할 것

- 세로 화면에서 가로 원본의 좌우가 잘리지 않았는지
- 가로 화면에서 세로 원본의 위아래가 잘리지 않았는지
- 얼굴·제품·화면 글씨가 프레임 밖으로 나가지 않았는지
- 자막이 3줄 이상으로 과도하게 줄바꿈되지 않았는지
- 자막이 플랫폼 버튼·설명 영역과 겹치지 않는지
- 원본 소리를 끄도록 적은 장면이 실제로 음소거되었는지
- 사진 캐시와 영상이 오프라인으로 표시되지 않는지

Basic Title은 영상 그래픽이므로 일반 내보내기에 표시됩니다. SRT나 접근성 Caption은 별도 용도입니다.

## 16. 수정 후 다시 만들기

1. Excel·Numbers·CSV에서 기획표를 수정하고 저장합니다.
2. 같은 프로젝트 폴더에서 검사 명령을 다시 실행합니다.
3. 오류가 없으면 생성 명령을 다시 실행합니다.
4. 새 XML을 Final Cut으로 가져와 기존 버전과 비교합니다.

```bash
source .venv/bin/activate
python make_xml.py projects/my-video --layout both --validate-only
python make_xml.py projects/my-video --layout both --preview-only
python make_xml.py projects/my-video --layout both
```

Final Cut에서 이미 수동으로 고친 프로젝트 위에 자동으로 덮어쓰는 방식은 아닙니다. 중요한 수동 편집이 있다면 새 프로젝트 이름이나 별도 Library에서 비교하세요.

## 17. 민감한 파일과 백업

- 실제 미디어와 기획표는 공개 GitHub 저장소에 올리지 않습니다.
- `projects/`와 `Generated/`는 `.gitignore` 대상인지 공개 전에 확인합니다.
- 출처가 불명확한 `.command`, `.pkg`, `.app`은 실행하지 않습니다.
- 배포자의 공식 저장소나 검증한 Release에서 코드를 받습니다.
- 작업 폴더 전체를 함께 백업합니다. XML만 따로 옮기면 미디어가 오프라인이 될 수 있습니다.

## 문제가 생기면

[문제 해결 문서](TROUBLESHOOTING.md)에서 오류 문구를 찾으세요. 해결되지 않으면 다음 네 가지를 함께 기록하면 원인 확인이 빠릅니다.

1. 실행한 명령
2. Terminal의 전체 오류 문구
3. 기획표 헤더와 문제가 난 행
4. `build_report.txt`
