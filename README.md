# CSV / Excel → Final Cut Pro XML

기획표 순서대로 사진·영상·Basic Title을 배치한 **편집 가능한 초안**을 만듭니다.
완성 영상 렌더러나 CSV와 Final Cut Pro의 양방향 동기화 도구는 아닙니다.

**0.6.2-rc1: 블로그 공개 전 검증 후보. 실제 Colab 브라우저와 Final Cut Pro 가져오기 확인 후 정식 공개하세요.**

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Kongdataif/csv-to-fcpxml-starter/blob/stabilize/blog-0.6.2/colab.ipynb)

[CSV 양식](templates/timeline.csv) · [Excel 양식](templates/timeline.xlsx) · [블로그용 가이드](docs/BLOG_GUIDE.md) · [공개 전 확인표](docs/RELEASE_CHECKLIST.md)

## 1. 기획표 준비

양식 파일을 열고 GitHub의 **Download raw file** 버튼으로 받습니다. CSV/XLSX 중 하나만 사용합니다.
양식의 파일명은 설명용입니다. 실제 원본 이름으로 바꾸세요. 원본 미디어는 양식에 포함되지 않습니다.
Excel은 `timeline` 시트를 읽습니다. 해당 시트가 없으면 활성 시트를 사용합니다.

| 열 | 입력 | 비우면 |
|---|---|---|
| 파일 | 확장자를 포함한 실제 파일명. 경로 제외 | 오류 |
| 영상 원본 시작 | 원본에서 가져올 시작 시간 | 시작·끝 둘 다 비우면 전체 영상 |
| 영상 원본 끝 | 원본에서 가져올 끝 시간 | 시작·끝 둘 다 비우면 전체 영상 |
| 사진 표시 시간(초) | 사진만 숫자로 입력. 예: 3, 2.5 | 3초 |
| 화면 자막 | 해당 장면의 Basic Title 문장 | 타이틀 없음 |
| 소리 | 사용 또는 끄기 | 영상 원본 소리 사용 |

영상은 시작·끝을 모두 입력하거나 모두 비웁니다. 사진은 영상 시작·끝을 비웁니다.
시간은 초 숫자, `MM:SS`, `HH:MM:SS.mmm`로 적습니다. 완성 타임라인의 배치 시간이 아니라 **원본에서 사용할 구간**입니다.
길이는 30fps 단위로 반올림합니다. 원본 끝을 넘는 경우 남은 전체 프레임 수까지만 사용합니다.
CSV는 UTF-8로 저장합니다. Excel 수식·오류·날짜 셀 대신 직접 값을 입력하세요.
Numbers: [파일 > 다음으로 내보내기 > Excel](https://support.apple.com/guide/numbers/export-to-excel-or-another-file-format-tan3b922d4ad/mac).

```csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
intro.mov,00:00:01.000,00:00:05.000,,첫 장면,사용
photo.jpg,,,3,사진 장면,
outro.mp4,00:00:02.000,00:00:07.000,,마지막 장면,끄기
```

4초 + 3초 + 5초 = 12초입니다. 같은 사진을 다른 시간으로 재사용할 수 있습니다.
완전히 빈 행은 무시하지만, 자막·시간이 있는데 파일명만 빠진 행은 오류로 알려줍니다.
한글 파일명의 NFC/NFD 차이는 처리하며, 정규화 후 중복 이름은 거부합니다.

## 2. Google Colab

상단 **Open in Colab**에서 1~5번 셀을 순서대로 실행합니다. 코드 ZIP 설치는 필요하지 않습니다.

1. 고정 커밋의 코드·패키지 준비. 이 셀을 재실행하면 새 작업 세션이 시작됩니다.
2. 기획표 한 개 업로드. **기획표 저장 완료**와 장면 목록을 확인합니다.
3. 기획표의 사진·영상 전체 업로드. **미디어 저장 완료**를 확인합니다.
4. `LAYOUT`, `FIT` 설정 후 변환합니다. 오류가 나면 이 단계에서 중단합니다.
5. `fcpxml-result.zip`을 다운로드합니다. 이번 실행의 검증된 성공 결과만 받을 수 있습니다.

| 설정 | 값 |
|---|---|
| LAYOUT | portrait: 세로 1080×1920 / landscape: 가로 1920×1080 / both: 둘 다 |
| FIT | fit: 전체 표시·여백 가능 / fill: 화면 채움·가장자리 잘림 가능 |

CPU 런타임으로 실행합니다. `PROJECT_NAME`, `SUBTITLE_MODE`, `EXPORT_SRT`, `OK` 입력 단계는 없습니다.
노트북의 `CORE_REV`는 실행 코드를 고정한 커밋입니다. `main`을 자동으로 pull하지 않습니다.
원본은 Google 실행 환경에 업로드됩니다. 민감하거나 큰 파일은 Mac 로컬에서 처리하세요.
Colab은 영구 파일 보관소가 아닙니다. [Colab FAQ](https://research.google.com/colaboratory/faq.html)

## 3. Mac 로컬

Python 3.10 이상, Git, FFmpeg가 필요합니다. VS Code 터미널에서도 실행할 수 있습니다.

```bash
brew install ffmpeg
git clone --branch stabilize/blog-0.6.2 https://github.com/Kongdataif/csv-to-fcpxml-starter.git
cd csv-to-fcpxml-starter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

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
# 세로와 가로 둘 다:
python run.py my-video --layout both --fit fill
```

## 4. 결과와 Final Cut Pro

Colab ZIP을 풀면 다음 구조입니다. Mac 로컬에서는 `my-video` 안에 같은 `output`이 생성됩니다.

```text
fcpxml-result/
├── timeline.csv                # XLSX 입력이면 timeline.xlsx
├── Media/                      # 사용한 원본 포함
└── output/
    ├── portrait.fcpxml         # 선택한 방향만 생성
    ├── landscape.fcpxml        # landscape/both 선택 시
    ├── timeline_converted.csv  # XLSX 입력일 때만
    ├── build_report.json       # 버전·설정·검증 범위·파일 해시
    └── media/                  # 사진을 지정 시간의 MP4로 변환한 캐시
```

`파일 > 가져오기 > XML`에서 사용할 방향의 FCPXML을 가져옵니다.
출력은 FCPXML 1.14, 30fps입니다. Apple은 [Final Cut Pro 12.0에서 FCPXML 1.14 도입](https://support.apple.com/en-us/102825)을 명시합니다.
[Apple XML 가져오기 안내](https://support.apple.com/guide/final-cut-pro/import-and-export-xml-verdbd66ae/mac)

**XML만 따로 옮기지 마세요.** `Media`와 `output/media`를 함께 유지합니다.
사진 장면은 원본 PNG/JPG가 아니라 MP4 캐시를 참조합니다. 해당 캐시도 보관해야 합니다.
기본 자막은 Basic Title입니다. SRT나 clean/with_titles 두 가지 XML은 만들지 않습니다.
누락 미디어가 있으면 [원본 미디어 다시 연결](https://support.apple.com/guide/final-cut-pro/relink-clips-to-media-files-ver26f5c8c9/mac)을 사용합니다.
결과 ZIP에 사용한 원본도 들어 있으므로 다른 사람에게 공유하기 전에 내용을 확인하세요.

## 5. 다시 실행할 때

기획표 변경: 2번부터, 원본 변경: 3번부터, 화면 설정 변경: 4번부터 진행합니다.
1번 재실행은 새 작업이므로 파일을 다시 업로드합니다.
성공 후 입력·결과 파일이 바뀌었거나 마지막 변환이 실패했다면 다운로드를 차단합니다.

실패한 변환은 이전 성공 XML을 덮어쓰지 않습니다.
새 변환이 성공하면 `output`을 교체하고 이전 폴더는 `.previous-output-<식별자>`로 남깁니다.
ZIP에는 이전 출력, 미사용 원본, 실패 중간 파일이 들어가지 않습니다.
이전 결과로 작업 중인 Final Cut Pro 프로젝트의 폴더에 새 결과를 덮어쓰지 마세요.
매번 별도 작업 폴더에 압축을 풀고 기존 원본 경로를 유지하세요. CSV 재실행은 기존 편집에 변경을 병합하지 않습니다.

## 6. 지원과 한계

입력 확장자: MOV, MP4, M4V, MKV, AVI / JPG, JPEG, PNG, HEIC, TIF, TIFF.
확장자 허용은 모든 코덱의 Final Cut Pro 호환을 보장하지 않습니다. HEIC 등은 FFmpeg 빌드에 따라 디코딩이 실패할 수 있습니다. 이때는 JPG/PNG로 내보내세요.
HDR 색 관리, 회전 메타데이터, 가변 FPS, 긴 자막·화면 잘림은 실제 원본으로 확인해야 합니다.
사진은 H.264 MP4로 변환하므로 투명도·원본 사진 편집 기능이 그대로 유지되지 않습니다.
음악, 장면 전환, 완성 영상 렌더링, 별도 자막 파일, 양방향 동기화는 범위 밖입니다.

자동 검증은 XML 파싱, 리소스 참조, 해상도/FPS, 시간, 파일 경로·해시입니다.
**전체 Apple DTD 검증과 실제 Final Cut Pro 가져오기 성공을 대신하지 않습니다.**

## 개발·검증

```bash
python -m unittest discover -s tests -v
```

GitHub Actions는 Python 3.10/3.13에서 테스트하도록 구성했습니다. 실제 실행 결과는 PR의 Checks에서 확인하세요.
수동 확인 범위는 [공개 전 확인표](docs/RELEASE_CHECKLIST.md)를 따릅니다.
라이선스: MIT. 사용자 원본 미디어는 저장소에 커밋하지 마세요.
