# CSV → Final Cut Pro XML

CSV에 적은 순서대로 사진과 영상을 연결해 Final Cut Pro용 `.fcpxml`을 만듭니다.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Kongdataif/csv-to-fcpxml-starter/blob/main/colab.ipynb)

## 먼저 구분하세요

입력은 두 종류이며 저장 위치가 서로 다릅니다.

```text
my-video/
├── timeline.csv       ← 편집 순서를 적은 CSV는 여기에
└── Media/             ← CSV에 적은 사진·영상은 여기에
    ├── intro.mov
    ├── photo.jpg
    └── outro.mp4
```

> `timeline.csv`를 `Media` 안에 넣지 마세요. 사진과 영상을 `my-video` 바로 아래에 넣지도 마세요.

## Mac에서 실행

### 1. 처음 한 번만 준비

Python 3.10 이상과 FFmpeg가 필요합니다. 별도 Python 패키지는 설치하지 않습니다.

```bash
brew install ffmpeg
git clone https://github.com/Kongdataif/csv-to-fcpxml-starter.git
cd csv-to-fcpxml-starter
```

이미 저장소를 내려받았다면 다음부터는 해당 폴더에서 `git pull`만 실행합니다.

### 2. CSV 준비

[my-video/timeline.csv](my-video/timeline.csv)를 Excel 또는 Numbers로 열어 실제 파일명과 편집 내용을 적습니다. 다른 CSV를 사용하는 경우 파일명을 `timeline.csv`로 바꾸고 `my-video` 바로 아래에 놓습니다.

### 3. 미디어 준비

CSV의 `파일` 열에 적은 사진과 영상을 `my-video/Media`에 넣습니다. 안내용 `여기에_사진과_영상을_넣으세요.txt`는 삭제해도 됩니다.

### 4. 실행

```bash
python3 run.py my-video --layout portrait --fit fit
```

### 5. 결과 확인

```text
my-video/output/
├── portrait.fcpxml       # --layout portrait 또는 both
├── landscape.fcpxml      # --layout landscape 또는 both
└── media/                # 사진을 영상으로 바꾼 호환용 파일
```

Final Cut Pro에서 `파일 > 가져오기 > XML`을 선택해 `.fcpxml`을 불러옵니다.

## 실행 파라미터

```bash
python3 run.py [프로젝트 폴더] [--layout 값] [--fit 값]
```

| 파라미터 | 선택값 | 기본값 | 의미 |
|---|---|---|---|
| `프로젝트 폴더` | 폴더 경로 | `my-video` | `timeline.csv`와 `Media/`가 함께 들어 있는 폴더입니다. CSV 파일 경로를 넣는 자리가 아닙니다. |
| `--layout` | `portrait` | `portrait` | 세로 9:16, 1080×1920 FCPXML을 만듭니다. |
| `--layout` | `landscape` |  | 가로 16:9, 1920×1080 FCPXML을 만듭니다. |
| `--layout` | `both` |  | 세로와 가로 FCPXML을 모두 만듭니다. |
| `--fit` | `fit` | `fit` | 원본 전체를 보여줍니다. 화면 비율이 다르면 여백이 생길 수 있습니다. |
| `--fit` | `fill` |  | 화면을 가득 채웁니다. 원본 가장자리가 잘릴 수 있습니다. |

프로젝트 폴더와 옵션을 모두 생략하면 `my-video`, 세로 화면, 전체 보기를 사용합니다.

```bash
python3 run.py
```

세로와 가로를 모두 만들고 화면을 채우는 예:

```bash
python3 run.py my-video --layout both --fit fill
```

터미널에서 전체 파라미터 설명을 다시 보려면 다음을 실행합니다.

```bash
python3 run.py --help
```

## timeline.csv 작성법

헤더 이름은 바꾸지 말고 UTF-8 CSV로 저장합니다. 한 행이 Final Cut 타임라인의 한 장면입니다.

| 열 | 필수 여부 | 입력 방법 | 빈칸일 때 |
|---|---|---|---|
| `파일` | 필수 | `Media` 안의 실제 파일명과 확장자를 정확히 입력 | 오류 |
| `영상 원본 시작` | 선택 | 영상에서 사용할 시작 시간 | 끝도 비어 있으면 영상 처음부터 사용 |
| `영상 원본 끝` | 선택 | 영상에서 사용할 끝 시간 | 시작도 비어 있으면 영상 끝까지 사용 |
| `사진 표시 시간(초)` | 선택 | 사진을 보여줄 초. 예: `3`, `2.5` | 사진은 3초 |
| `화면 자막` | 선택 | 해당 장면 동안 표시할 문장 | 자막 없음 |
| `소리` | 선택 | 영상은 `사용` 또는 `끄기` | 사용할 수 있는 원본 소리 사용 |

시간은 `초`, `MM:SS`, `HH:MM:SS.mmm` 형식을 사용할 수 있습니다. 영상의 시작과 끝은 둘 다 입력하거나 둘 다 비워야 합니다. 사진에는 영상 시작·끝을 입력하지 않습니다.

```csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
intro.mov,00:00:01.000,00:00:04.000,,첫 장면,사용
photo.jpg,,,3,사진 장면,
outro.mp4,,,,마지막 장면,끄기
```

위 파일명은 설명용입니다. `Media`에 실제로 넣은 파일명으로 반드시 바꾸세요.

## Colab에서 실행

상단의 **Open in Colab** 버튼을 누르고 셀을 위에서 아래로 실행합니다. 업로드는 다음처럼 분리되어 있습니다.

1. 실행 코드 준비
2. CSV 한 개 업로드 — 어떤 이름의 `.csv`를 골라도 `my-video/timeline.csv`로 저장
3. 사진·영상 업로드 — 선택한 파일은 `my-video/Media/`에 저장
4. `LAYOUT`과 `FIT` 선택 후 변환
5. 결과 ZIP 다운로드

각 업로드 셀은 저장된 위치와 파일 목록을 출력합니다. ZIP에는 FCPXML이 참조하는 원본 미디어도 포함되므로 영상이 크면 다운로드 파일도 커집니다.

## 지원 범위

- 영상: MOV, MP4, M4V, MKV, AVI
- 사진: JPG, JPEG, PNG, HEIC, TIF, TIFF
- 프로젝트: 30fps, 세로 또는 가로
- 출력: Final Cut Pro용 FCPXML 1.14

사진은 Final Cut 호환성을 위해 실행 중 H.264 영상으로 변환됩니다. 원본 영상은 다시 인코딩하지 않습니다.

## 라이선스

MIT License
