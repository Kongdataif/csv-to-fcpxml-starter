# 선택 경로 — Colab으로 기획표를 XML로 변환

브라우저에서 Excel 또는 CSV 기획표와 사진·영상을 직접 올려 Final Cut Pro용 FCPXML을 만드는 순서입니다. Python, Git, GitHub 계정과 별도 프로그램 설치는 필요하지 않습니다. Colab 실행에는 Google 계정 로그인이 필요할 수 있습니다.

> 이 문서는 이미 공개된 도구의 일반 사용자용입니다. Starter ZIP과 GitHub ID는 필요하지 않으며, 업로드하지도 않습니다.

> Windows·Mac·Linux에서 XML을 만들 수 있습니다. 생성한 XML을 Final Cut Pro로 가져오고 영상을 내보내는 단계는 FCPXML 1.14를 지원하는 Final Cut Pro 11.2 이상이 설치된 Mac에서 진행합니다.

## 1. 파일 준비

필수:

- `timeline.xlsx` 또는 `timeline.csv` 한 개
- 기획표의 `파일` 열에 적은 사진과 영상

처음에는 [Excel·Numbers용 타임라인 양식](../templates/simple_timeline.xlsx)을 사용하세요. Excel은 `.xlsx`를 그대로 저장하고, Numbers는 편집한 뒤 `파일 > 다음으로 내보내기 > Excel`로 `.xlsx`를 만듭니다. `.numbers` 원본은 Colab에 직접 올리지 않습니다.

처음에는 다음 기본 6열을 사용합니다.

~~~csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
cafe_boot.mov,00:00:12.000,00:00:16.000,,카페에서 첫 부팅,사용
ipad_drawing.png,,,3,아이패드로 그린 그림,
office.mp4,,,,회사에서도 이어서 사용,끄기
~~~

핵심 규칙:

1. 기획표에 보이는 행 순서대로 장면이 이어집니다.
2. `파일`은 실제 파일명·확장자·대소문자까지 같아야 합니다.
3. 영상 전체는 원본 시작·끝을 모두 비웁니다.
4. 영상 일부는 시작·끝을 모두 적습니다.
5. 사진은 원본 시간을 비우고 표시 초만 적습니다. 빈칸은 3초입니다.
6. `화면 자막`은 장면 전체에 보이며, 빈칸이면 자막이 없습니다.
7. 영상 `소리`는 빈칸·`사용`이면 원본 사용, `끄기`이면 제외합니다.

순서 번호, 방향별 화면 맞춤과 메모가 필요하면 [사용자 가이드의 화면 맞춤 선택 열](USER_GUIDE.md#8-화면-맞춤-선택-열)을 참고하세요. CSV를 쓰는 경우에만 `CSV UTF-8`로 저장합니다.

## 2. Colab 열기

1. 저장소 첫 화면의 **Google Colab에서 열기** 버튼을 누릅니다.
2. 주소가 `colab.research.google.com`인지 확인합니다.
3. 상단 메뉴에서 `런타임 > 모두 실행`을 선택합니다.

무료 기본 CPU 런타임이면 충분합니다. GPU를 켤 필요는 없습니다.

## 3. 설정 확인

처음에는 프로젝트 이름과 화면 방향만 정하고 나머지는 기본값을 권장합니다.

| 설정 | 의미 | 처음 권장 |
|---|---|---|
| `PROJECT_NAME` | 결과 파일 이름 | 작업 이름으로 변경 |
| `OUTPUT_FORMAT` | `portrait` 세로, `landscape` 가로, `both` 둘 다 | 기본은 `portrait`; 두 규격이 모두 필요하면 `both` |
| `FPS` | 프로젝트 프레임률 | 모르면 `30` |
| `SUBTITLE_MODE` | 자막 결과 방식 | 일반 영상은 `title` |
| `EXPORT_SRT` | 별도 SRT 생성 | `True` |
| `DEFAULT_PHOTO_DURATION` | 사진 시간 빈칸의 기본 초 | `3` |
| `USE_SEPARATE_SUBTITLES_CSV` | 정밀 자막 CSV 추가 업로드 | 보통 `False` |

`title`은 Final Cut의 Basic Title 영상 그래픽입니다. 평소처럼 Share하면 영상에 보입니다. `caption`은 접근성·언어 선택 트랙을 위한 고급 모드입니다.

## 4. 파일 업로드

노트북이 다음 순서로 파일 선택 창을 엽니다.

### ① timeline.xlsx 또는 timeline.csv

기획표 하나만 선택합니다. Excel은 `.xlsx`를 그대로 올리고, Numbers는 `파일 > 다음으로 내보내기 > Excel`로 저장한 `.xlsx`를 올립니다. UTF-8 `.csv`도 사용할 수 있습니다.

`.numbers` 원본과 사진·영상은 이 창에 올리지 않습니다. 사진·영상은 기획표 확인 후 다음 창에서 올립니다.

### ② subtitles.xlsx 또는 subtitles.csv — 설정했을 때만

한 장면 안에서 자막이 여러 번 바뀌어 `USE_SEPARATE_SUBTITLES_CSV = True`로 설정했을 때만 나타납니다. [정밀 자막 Excel 양식](../templates/subtitles_template.xlsx) 또는 CSV 양식 중 하나를 사용하고, 기본 기획표의 `화면 자막`은 모두 비워 둡니다.

### ③ 기획표 내용 확인

기획표를 올리면 미디어 업로드 전에 `순서`, `파일`, `사용 구간 / 표시 시간`, `화면 자막`이 표로 보입니다. 별도 자막 기획표를 썼다면 정밀 자막 표도 함께 보입니다.

- 한글, 줄바꿈, 파일명과 자막 문구가 정상인지 확인합니다.
- CSV의 글자가 `???` 또는 낯선 문자로 깨졌다면 진행하지 말고 `.xlsx` 양식을 다시 받거나 `CSV UTF-8`로 다시 저장합니다.
- 정상이라면 입력란에 `OK`를 입력합니다.

이 표는 자막 문구와 장면 연결을 확인하는 화면입니다. 정확한 폰트·크기·위치·윤곽선은 `*_with_titles.fcpxml`을 Final Cut Pro로 가져온 뒤 확인합니다.

### ④ 사진과 영상

기획표의 `파일` 열에 적은 사진과 영상을 모두 선택합니다. `Command` 또는 `Ctrl`을 누른 채 여러 파일을 고를 수 있습니다.

폴더 ZIP이나 Python 파일을 올리지 않습니다. 사진인지 영상인지는 자동으로 판별합니다.

## 5. 검사 결과 확인

생성 전 요약에서 다음을 확인합니다.

- 기획표 장면 수
- 업로드한 미디어 수와 연결된 수
- 자동 판별한 영상·사진 수
- 영상 오디오 유무
- 예상 완성 길이
- 오류 또는 경고

오류는 결과를 추측해서 만들지 않고 중단한 상태입니다. 표시된 기획표 행과 수정 안내를 읽고 파일을 고친 뒤 `런타임 > 다시 시작 및 모두 실행`로 다시 올립니다.

경고는 결과를 만들 수 있지만 확인이 필요한 상태입니다. 예를 들어 프레임 경계에 맞추며 길이가 아주 조금 보정되거나, 사진 행의 소리 값을 무시한 경우입니다.

## 6. 결과 다운로드

성공하면 `프로젝트명_FinalCut_Result.zip`이 다운로드됩니다.

~~~text
MyVideo_FinalCut_Result.zip
├─ manifest.json
└─ Generated/
   ├─ vertical_9x16/                # portrait 또는 both
   │  ├─ MyVideo_vertical_9x16_clean.fcpxml
   │  ├─ MyVideo_vertical_9x16_with_titles.fcpxml
   │  ├─ MyVideo_vertical_9x16.srt
   │  ├─ build_report.txt
   │  └─ .build_media/
   └─ horizontal_16x9/              # landscape 또는 both
      ├─ MyVideo_horizontal_16x9_clean.fcpxml
      ├─ MyVideo_horizontal_16x9_with_titles.fcpxml
      ├─ MyVideo_horizontal_16x9.srt
      ├─ build_report.txt
      └─ .build_media/
~~~

`manifest.json`은 결과 파일명, 크기와 SHA-256을 기록한 확인표입니다. 업로드한 원본 파일 자체와 실행 파일은 결과 ZIP에 들어가지 않습니다. 다만 사진을 사용하면 `.build_media` MP4에 사진 화면이 들어가고, XML·SRT·보고서에는 파일명·자막·메모가 남을 수 있으므로 결과 ZIP도 민감하게 보관하세요.

## 7. Mac에서 폴더 복원

ZIP의 `Generated`를 원래 `Media` 옆에 놓습니다.

~~~text
MyVideo/
├─ timeline.xlsx
├─ Media/
│  ├─ cafe_boot.mov
│  ├─ ipad_drawing.png
│  └─ office.mp4
└─ Generated/
   ├─ vertical_9x16/
   │  ├─ MyVideo_vertical_9x16_with_titles.fcpxml
   │  └─ .build_media/
   └─ horizontal_16x9/
      ├─ MyVideo_horizontal_16x9_with_titles.fcpxml
      └─ .build_media/
~~~

XML만 Downloads에 따로 두거나 `Media`와 원본 파일 이름을 바꾸면 Final Cut에서 미디어가 오프라인으로 보일 수 있습니다. 사진을 사용했다면 `.build_media`도 이동하거나 삭제하지 않습니다.

## 8. Final Cut Pro로 가져오기

1. FCPXML 1.14를 지원하는 Final Cut Pro 11.2 이상을 엽니다.
2. 테스트할 Library와 Event를 선택합니다.
3. `File > Import > XML`을 선택합니다.
4. 세로는 `vertical_9x16`, 가로는 `horizontal_16x9` 폴더를 엽니다.
5. `*_with_titles.fcpxml`이 있으면 이를 선택하고, 자막이 없어서 생성되지 않았다면 `*_clean.fcpxml`을 선택합니다.
6. `both`를 선택했다면 두 XML을 각각 가져옵니다.
7. 사진·영상 순서, 길이, 소리, 화면 맞춤과 자막을 확인합니다.
8. 수정이 끝나면 `File > Share`로 최종 영상을 내보냅니다.

FCPXML 1.14는 Final Cut Pro 11.2에서 도입됐습니다. 이후 호환 버전에서도 사용할 수 있지만 실제 대상 Mac에서 짧은 테스트 프로젝트로 확인하세요. [Apple Final Cut Pro 릴리스 노트](https://support.apple.com/102825)

## 9. 민감하거나 큰 파일

Colab은 선택한 기획표와 미디어를 Google의 임시 실행 환경에 업로드합니다. Google Drive를 연결하지는 않지만, 파일이 내 컴퓨터 안에서만 처리되는 방식은 아닙니다.

다음 경우에는 [Mac 로컬 실행](MAC.md)을 사용하세요.

- 회사 기밀·NDA·공개 전 원본
- 민감한 얼굴·음성·주소·위치 정보
- 수 GB 이상의 4K·ProRes 영상
- 같은 프로젝트를 여러 번 다시 만드는 작업

작업이 끝나면 결과를 받은 뒤 `런타임 > 연결 해제 및 런타임 삭제`를 선택합니다.

## 더 자세히 보기

- 기획표 열과 사진·영상 예시: [사용자 가이드](USER_GUIDE.md)
- 오류별 해결: [문제 해결](TROUBLESHOOTING.md)
- 기밀·대용량 자료: [Mac 로컬 실행](MAC.md)
- 정밀 타임라인·BGM·dB: [고급 입력 형식](INPUT_FORMAT.md)
