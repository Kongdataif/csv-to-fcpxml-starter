# CSV / Excel → Final Cut Pro XML

기획표 순서대로 사진과 영상을 연결해 Final Cut Pro용 `.fcpxml`을 생성합니다.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Kongdataif/csv-to-fcpxml-starter/blob/main/colab.ipynb)

## 파일

```text
my-video/
├── timeline.csv       # 또는 timeline.xlsx
└── Media/
    ├── intro.mov
    ├── photo.jpg
    └── outro.mp4
```

- 기획표: `my-video/timeline.csv` 또는 `my-video/timeline.xlsx`
- 미디어: `my-video/Media/`
- CSV와 XLSX 중 하나만 사용

## 기획표 형식

| 형식 | 처리 |
|---|---|
| `timeline.csv` | UTF-8 CSV를 직접 사용 |
| `timeline.xlsx` | `output/timeline_converted.csv`로 자동 변환 |
| `.numbers` | Numbers에서 Excel 또는 CSV로 내보내기 |

XLSX의 `timeline` 시트를 사용합니다. 해당 시트가 없으면 활성 시트를 사용합니다.

Numbers: `파일 > 다음으로 내보내기 > Excel` → `timeline.xlsx`
[Apple Numbers 내보내기 안내](https://support.apple.com/guide/numbers/export-to-excel-or-another-file-format-tan3b922d4ad/mac)

## Mac

```bash
brew install ffmpeg
git clone https://github.com/Kongdataif/csv-to-fcpxml-starter.git
cd csv-to-fcpxml-starter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

기획표와 미디어를 위 구조로 배치한 후 실행합니다.

```bash
python run.py my-video --layout portrait --fit fit
```

결과:

```text
my-video/output/
├── portrait.fcpxml
├── landscape.fcpxml
├── timeline_converted.csv  # XLSX 입력일 때
└── media/                   # 사진 변환 파일
```

Final Cut Pro: `파일 > 가져오기 > XML`

## 옵션

```bash
python run.py [프로젝트 폴더] [--layout 값] [--fit 값]
```

| 옵션 | 값 | 기본값 | 결과 |
|---|---|---|---|
| 프로젝트 폴더 | 폴더 경로 | `my-video` | 기획표와 `Media/`가 있는 폴더 |
| `--layout` | `portrait` | `portrait` | 세로 1080×1920 |
| `--layout` | `landscape` |  | 가로 1920×1080 |
| `--layout` | `both` |  | 세로와 가로 |
| `--fit` | `fit` | `fit` | 원본 전체 표시, 여백 가능 |
| `--fit` | `fill` |  | 화면 채움, 가장자리 잘림 가능 |

```bash
python run.py my-video --layout both --fit fill
python run.py --help
```

## 기획표 열

| 열 | 입력 | 빈칸 |
|---|---|---|
| `파일` | `Media` 안의 파일명 | 허용하지 않음 |
| `영상 원본 시작` | 영상 시작 시간 | 끝도 비면 영상 처음 |
| `영상 원본 끝` | 영상 끝 시간 | 시작도 비면 영상 끝 |
| `사진 표시 시간(초)` | `3`, `2.5` 등 | 3초 |
| `화면 자막` | 장면 자막 | 자막 없음 |
| `소리` | `사용` 또는 `끄기` | 원본 소리 |

시간 형식: `초`, `MM:SS`, `HH:MM:SS.mmm`

```csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
intro.mov,00:00:01.000,00:00:04.000,,첫 장면,사용
photo.jpg,,,3,사진 장면,
outro.mp4,,,,마지막 장면,끄기
```

예제 파일명은 `Media`의 실제 파일명으로 교체합니다.

## Colab

상단의 **Open in Colab**에서 다음 셀을 순서대로 실행합니다.

1. 코드와 패키지 설치
2. CSV 또는 XLSX 한 개 업로드
3. 사진·영상 업로드
4. `LAYOUT`, `FIT` 설정 후 변환
5. 결과 ZIP 다운로드

XLSX 중간 CSV: `my-video/output/timeline_converted.csv`

## 지원

- Python 3.10 이상
- FFmpeg
- 기획표: CSV, XLSX
- 영상: MOV, MP4, M4V, MKV, AVI
- 사진: JPG, JPEG, PNG, HEIC, TIF, TIFF
- 출력: FCPXML 1.14, 30fps

## 라이선스

MIT
