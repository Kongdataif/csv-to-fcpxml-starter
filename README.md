# CSV / Excel → Final Cut Pro XML

기획표 순서대로 사진·영상과 화면 자막을 배치한 **편집 가능한 타임라인 초안**을 만듭니다.
생성한 FCPXML을 Mac의 Final Cut Pro로 가져와 편집합니다. 완성 영상 내보내기나 CSV와 Final Cut Pro의 양방향 동기화는 지원하지 않습니다.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Kongdataif/csv-to-fcpxml-starter/blob/main/colab.ipynb)

[CSV 양식](templates/timeline.csv) · [Excel 양식](templates/timeline.xlsx)

## 1. 기획표 준비

양식 파일을 열고 **Download raw file** 버튼으로 내려받습니다. CSV와 XLSX 중 하나만 사용하세요.
양식의 예시 파일명은 실제 사용할 원본 이름으로 바꿉니다. 원본 미디어는 양식에 포함되어 있지 않습니다.

| 열 | 입력할 내용 | 비워두면 |
|---|---|---|
| 파일 | 확장자를 포함한 실제 파일명. 폴더 경로는 제외 | 오류 |
| 영상 원본 시작 | 원본 영상에서 사용할 구간의 시작 | 시작·끝을 모두 비우면 영상 전체 사용 |
| 영상 원본 끝 | 원본 영상에서 사용할 구간의 끝 | 시작·끝을 모두 비우면 영상 전체 사용 |
| 사진 표시 시간(초) | 사진을 보여줄 시간. 예: 3, 2.5 | 3초 |
| 화면 자막 | 해당 장면에 표시할 문장 | 자막 없음 |
| 소리 | 사용 또는 끄기 | 영상 원본 소리 사용 |

영상은 시작·끝을 모두 입력하거나 모두 비웁니다. 사진은 영상 시작·끝을 비우고 사진 표시 시간만 입력합니다.
시간은 초 숫자, `MM:SS`, `HH:MM:SS.mmm` 형식으로 적습니다. **완성 영상의 배치 시간이 아니라 원본에서 가져올 구간**입니다.
`1`과 `00:00:01`은 모두 원본의 1초 지점입니다. `12.5`처럼 소수 초도 사용할 수 있습니다. `1초`처럼 단위는 붙이지 않습니다.
장면은 기획표 위에서 아래 순서대로 이어집니다.

`소리`를 `끄기`로 지정한 영상은 생성한 타임라인에서 오디오 구성요소를 비활성화합니다.
원본 파일의 소리는 그대로 보존됩니다. 이미 가져온 Final Cut Pro 프로젝트에는 기획표 수정이 자동 반영되지 않으므로,
새로 변환한 XML을 가져오거나 편집 중인 클립의 오디오 인스펙터에서 **오디오 구성** 체크를 해제하세요.

```csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
intro.mov,00:00:01.000,00:00:05.000,,첫 장면,사용
photo.jpg,,,3,사진 장면,
outro.mp4,00:00:02.000,00:00:07.000,,마지막 장면,끄기
```

위 예시는 4초 + 3초 + 5초, 총 12초입니다. 같은 원본을 여러 행에서 다시 사용할 수 있습니다.
완전히 빈 행은 건너뛰지만, 자막이나 시간이 있는데 파일명이 빠진 행은 오류로 표시합니다.
길이는 30fps의 프레임 단위로 조정되므로 입력한 소수점 시간과 약간 달라질 수 있습니다.

CSV는 **UTF-8**로 저장하세요. Excel은 `timeline` 시트를 읽고, 없으면 활성 시트를 사용합니다.
Excel에는 수식·오류·날짜 셀 대신 값을 직접 입력합니다.
Numbers에서는 **파일 > 다음으로 내보내기 > Excel**로 `.xlsx`를 만듭니다. `.numbers`는 직접 읽지 않습니다.
Numbers에서 CSV로 내보낼 때는 **‘표 이름 포함’을 해제**하고 기획표 한 개만 내보내세요. CSV 첫 줄은 `파일,영상 원본 시작,…`이어야 합니다.
첫 줄에 `표 1` 같은 표 이름이나 빈 줄이 들어 있으면 제거한 뒤 업로드합니다. [Numbers 내보내기 안내](https://support.apple.com/ko-kr/guide/numbers/tan3b922d4ad/mac)

## 2. Google Colab에서 실행

상단 **Open in Colab** 버튼을 누르고 1~5번 셀을 순서대로 실행합니다. 별도의 코드 ZIP은 필요하지 않습니다.

| 단계 | 할 일 | 완료 확인 |
|---|---|---|
| 1 | 실행 코드와 패키지 준비 | 새 작업 폴더 경로 |
| 2 | CSV 또는 XLSX 한 개 업로드 | 기획표 저장 완료와 장면 목록 |
| 3 | 기획표에 적은 사진·영상 전체 업로드 | 미디어 저장 완료 |
| 4 | LAYOUT과 FIT 설정 후 변환 | 변환·결과 검증 완료 |
| 5 | 결과 다운로드 | fcpxml-result.zip |

각 단계의 완료 표시를 확인한 뒤 다음 셀을 실행하세요.

| 설정 | 값 | 의미 |
|---|---|---|
| LAYOUT | portrait | 세로 1080×1920 |
| LAYOUT | landscape | 가로 1920×1080 |
| LAYOUT | both | 세로와 가로 각각 생성 |
| FIT | fit | 원본 전체 표시. 비율이 다르면 여백 가능 |
| FIT | fill | 화면을 채움. 원본 가장자리 잘림 가능 |

CPU 런타임으로 실행하면 됩니다. GPU는 필요하지 않습니다.
원본은 Google 실행 환경에 업로드되므로 민감하거나 큰 파일은 Mac 로컬에서 처리하세요.
Colab은 영구 보관소가 아니므로 결과 ZIP이 Mac에 다운로드되었는지 확인하세요.

## 3. Mac 로컬에서 실행

Python 3.10 이상, Git, FFmpeg가 필요합니다. VS Code 터미널에서도 실행할 수 있습니다.
Homebrew를 사용하는 Mac에서는 다음과 같이 준비합니다.

```bash
brew install ffmpeg
git clone --branch main https://github.com/Kongdataif/csv-to-fcpxml-starter.git
cd csv-to-fcpxml-starter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`my-video`에 기획표 하나와 `Media` 폴더를 둡니다.

```text
my-video/
├── timeline.csv          # 또는 timeline.xlsx, 둘 중 하나만
└── Media/
    ├── intro.mov
    ├── photo.jpg
    └── outro.mp4
```

```bash
python run.py my-video --layout portrait --fit fit
```

세로와 가로를 함께 만들려면 다음 명령을 사용합니다.

```bash
python run.py my-video --layout both --fit fit
```

## 4. Final Cut Pro로 가져오기

Colab 결과 ZIP은 새 폴더에 압축을 풉니다. Mac 로컬에서는 `my-video` 안에 `output`이 생성됩니다.

```text
작업 폴더/
├── timeline.csv                # XLSX 입력이면 timeline.xlsx
├── Media/                      # 기획표에서 사용한 원본
└── output/
    ├── portrait.fcpxml         # portrait 또는 both 선택 시
    ├── landscape.fcpxml        # landscape 또는 both 선택 시
    ├── timeline_converted.csv  # XLSX 입력일 때만
    ├── build_report.json       # 변환 설정과 파일 검사 정보
    └── media/                  # 사진을 MP4로 변환한 파일
```

Final Cut Pro 12.0 이상에서 **파일 > 가져오기 > XML**을 선택합니다.
`output` 안의 사용할 방향의 FCPXML을 가져옵니다. `both`로 만들었다면 두 XML을 각각 가져올 수 있습니다.
출력은 FCPXML 1.14, 30fps입니다.

**XML만 따로 옮기지 마세요.** `Media`와 `output/media`를 함께 보관합니다.
사진 장면은 원본 사진이 아니라 지정한 길이의 MP4 변환 파일을 참조하므로 `output/media`를 삭제하면 안 됩니다.
미디어가 누락되면 **파일 > 파일 다시 연결 > 원본 미디어**에서 해당 파일을 다시 지정합니다.
사진 장면에는 원본 PNG/JPG 대신 `output/media`의 해당 MP4를 연결합니다.

화면 자막은 캡션 트랙이 아니라 **Basic Title**로 생성됩니다. 문구·글꼴·위치는 Final Cut Pro에서 수정하세요.
별도 SRT는 생성하지 않습니다. 가져온 뒤 장면 순서, 구간, 소리, 자막과 화면 잘림을 확인하세요.
결과 ZIP에는 사용한 원본도 포함되므로 다른 사람에게 공유하기 전에 내용을 확인하세요.

## 5. 수정하거나 오류가 발생했을 때

Colab에서 기획표를 바꾸면 2번부터, 원본을 바꾸면 3번부터, 화면 설정만 바꾸면 4번부터 진행합니다.
1번을 다시 실행하면 새 작업이므로 파일을 다시 업로드해야 합니다.

| 상황 | 확인할 내용 |
|---|---|
| 파일을 찾을 수 없음 | 기획표와 원본의 이름·확장자가 같은지 확인 |
| 영상 시간 오류 | 시작·끝을 모두 입력했는지, 원본 길이 안의 구간인지 확인 |
| 기획표 첫 행에 ‘파일’ 열이 필요함 | 첫 줄의 표 이름·빈 줄을 제거. Numbers CSV 내보내기에서 ‘표 이름 포함’ 해제 |
| 기획표 행 오류 | 열 이름을 유지했는지, 파일명이 비어 있지 않은지 확인 |
| 다운로드 차단 | 업로드와 변환을 완료했는지, 성공 후 입력이나 결과가 바뀌지 않았는지 확인 |
| 사진 읽기 실패 | JPG 또는 PNG로 내보낸 뒤 다시 시도 |

실패한 변환은 이전 성공 XML을 덮어쓰지 않지만, 이전 결과를 이번 결과로 다운로드할 수도 없습니다.
새 변환이 성공하면 `output`이 교체되고 이전 폴더는 `.previous-output-<식별자>`로 남습니다.
ZIP에는 이전 출력, 미사용 원본, 실패 중간 파일이 포함되지 않습니다.

이미 Final Cut Pro에서 작업 중인 폴더에 새 결과를 덮어쓰지 마세요. 새 ZIP은 별도 폴더에 풉니다.
기획표를 다시 실행하면 새 초안이 만들어집니다. 기존 Final Cut Pro 편집에 변경 사항을 자동으로 합치지는 않습니다.

## 지원과 주의 사항

입력 확장자: MOV, MP4, M4V, MKV, AVI / JPG, JPEG, PNG, HEIC, TIF, TIFF.
확장자가 허용되어도 해당 파일의 코덱이 Final Cut Pro에서 지원되지 않을 수 있습니다.
HEIC 등 일부 사진은 FFmpeg 환경에 따라 읽기에 실패할 수 있습니다.
사진은 H.264 MP4로 변환되므로 투명도나 원본 사진 편집 기능이 그대로 유지되지 않습니다.
HDR, 회전 정보, 가변 FPS, 긴 자막과 화면 잘림은 실제 결과를 확인하고 조절하세요.

자동 검사는 XML 구조·시간·파일 경로 등을 확인합니다. Final Cut Pro에서의 최종 화면이나 가져오기 성공까지 보장하지는 않습니다.
음악, 장면 전환, 색 보정과 최종 영상 내보내기는 Final Cut Pro에서 진행합니다.

참고: [Apple XML 가져오기](https://support.apple.com/guide/final-cut-pro/import-and-export-xml-verdbd66ae/mac) · [Apple 미디어 다시 연결](https://support.apple.com/guide/final-cut-pro/relink-clips-to-media-files-ver26f5c8c9/mac) · [Numbers 내보내기](https://support.apple.com/guide/numbers/export-to-excel-or-another-file-format-tan3b922d4ad/mac) · [Colab FAQ](https://research.google.com/colaboratory/faq.html)

라이선스: MIT. 사용자 원본 미디어는 저장소에 업로드하지 마세요.
