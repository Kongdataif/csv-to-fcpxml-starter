# CSV → Final Cut Pro XML

`timeline.csv`에 장면 순서를 적고 `Media` 폴더에 사진·영상을 넣으면 Final Cut Pro용 `.fcpxml`을 만듭니다.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Kongdataif/csv-to-fcpxml-starter/blob/main/colab.ipynb)

## 가장 간단한 사용법

1. `my-video/Media`에 사진과 영상을 넣습니다.
2. `my-video/timeline.csv`에 파일명과 순서를 적습니다.
3. 터미널에서 실행합니다.

```bash
python3 run.py my-video --layout portrait --fit fit
```

결과는 `my-video/output/portrait.fcpxml`입니다. Final Cut Pro에서 `파일 > 가져오기 > XML`을 선택해 불러옵니다.

## 폴더 구조

```text
csv-to-fcpxml-starter/
├── run.py
└── my-video/
    ├── timeline.csv
    └── Media/
        ├── intro.mov
        ├── photo.jpg
        └── outro.mp4
```

`Media/여기에_사진과_영상을_넣으세요.txt`는 안내 파일입니다. 실제 작업을 시작할 때 삭제해도 됩니다.

## timeline.csv

Excel이나 Numbers에서 아래 열을 그대로 사용하고 UTF-8 CSV로 저장합니다.

| 열 | 입력 |
|---|---|
| `파일` | `Media` 안의 실제 파일명 |
| `영상 원본 시작` | 잘라 쓸 영상의 시작 시간. 전체 영상이면 빈칸 |
| `영상 원본 끝` | 잘라 쓸 영상의 끝 시간. 전체 영상이면 빈칸 |
| `사진 표시 시간(초)` | 사진을 보여줄 시간. 빈칸이면 3초 |
| `화면 자막` | 장면 위에 표시할 문장 |
| `소리` | `사용` 또는 `끄기` |

```csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
intro.mov,00:00:01.000,00:00:04.000,,첫 장면,사용
photo.jpg,,,3,사진 장면,
outro.mp4,,,,마지막 장면,끄기
```

## 화면 크기와 맞춤 방식

세로 9:16(1080×1920):

```bash
python3 run.py my-video --layout portrait
```

가로 16:9(1920×1080):

```bash
python3 run.py my-video --layout landscape
```

세로와 가로를 모두 생성:

```bash
python3 run.py my-video --layout both
```

- `--fit fit`: 원본 전체가 보입니다. 화면 비율이 다르면 여백이 생길 수 있습니다.
- `--fit fill`: 화면을 채웁니다. 원본 가장자리가 잘릴 수 있습니다.

## Mac 준비

Python 3.10 이상과 FFmpeg가 필요합니다. Python 패키지는 따로 설치하지 않습니다.

```bash
brew install ffmpeg
git clone https://github.com/Kongdataif/csv-to-fcpxml-starter.git
cd csv-to-fcpxml-starter
python3 run.py my-video --layout portrait
```

기존에 내려받았다면 폴더에서 다음만 실행합니다.

```bash
git pull
```

## Colab

위의 **Open in Colab** 버튼을 누른 뒤 셀을 위에서 아래로 실행합니다. `timeline.csv`와 사진·영상을 선택하면 결과 ZIP이 다운로드됩니다.

## 지원 범위

- 영상: MOV, MP4, M4V, MKV, AVI
- 사진: JPG, JPEG, PNG, HEIC, TIF, TIFF
- 프로젝트: 30fps, 세로 또는 가로
- 출력: Final Cut Pro용 FCPXML 1.14

사진은 호환성을 위해 실행 중 H.264 영상으로 변환됩니다. 원본 영상은 다시 인코딩하지 않습니다.

## 라이선스

MIT License
