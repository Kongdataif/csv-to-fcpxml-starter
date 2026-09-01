# 선택 검사 — 개발자가 GitHub 없이 Colab 확인

Mac 로컬 테스트를 통과한 뒤, 선택 경로인 Colab도 배포할 때만 수행합니다. GitHub에 공개하기 전에 **현재 Starter ZIP만으로 Colab 변환이 되는지** 확인하는 개발자용 검사이며 일반 사용자에게는 안내하지 않습니다.

## 준비물

1. `CSV_to_FCPXML_GitHub_Starter_0.6.0.zip`
2. [Excel 타임라인 양식](../templates/simple_timeline.xlsx) 또는 `timeline.csv` 한 개
3. 기획표의 `파일` 열에 적힌 테스트 사진·영상

예제 미디어는 저장소에 포함하지 않습니다. 개인정보가 없는 짧은 영상과 사진을 준비하고 실제 파일명에 맞춰 기획표를 작성하세요. 첫 검사는 `.xlsx`로 하고, 공개 전에 `.csv`로 한 번 더 반복해 호환성을 확인합니다.

~~~csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
test_video.mp4,,,,영상 테스트입니다,사용
test_photo.jpg,,,3,사진 테스트입니다,
~~~

실제 파일 이름도 정확히 `test_video.mp4`, `test_photo.jpg`여야 합니다. 다른 이름이라면 기획표 쪽을 바꿉니다.

## 1. 노트북 열기

1. Starter ZIP의 압축을 풉니다.
2. [CSV_to_FCPXML_Colab.ipynb](../notebooks/CSV_to_FCPXML_Colab.ipynb)를 찾습니다.
3. [Google Colab](https://colab.research.google.com/)을 엽니다.
4. `파일 > 노트 업로드`에서 이 `.ipynb`를 선택합니다.

노트북의 개발자 설정에서 `REPO_URL = ""`인 상태가 정상입니다. 아직 존재하지 않는 GitHub 주소를 넣거나 `configure_github.py`를 먼저 실행하지 마세요.

처음 권장 설정:

~~~python
PROJECT_NAME = "DevSmoke"
OUTPUT_FORMAT = "both"
SUBTITLE_MODE = "title"
EXPORT_SRT = True
USE_SEPARATE_SUBTITLES_CSV = False
~~~

## 2. 모두 실행하고 업로드·미리보기 확인

상단 메뉴에서 `런타임 > 모두 실행`을 누릅니다.

| 순서 | 업로드 창 | 선택할 파일 |
|---|---|---|
| ① | `Starter ZIP 선택` | `CSV_to_FCPXML_GitHub_Starter_0.6.0.zip` 한 개 |
| ② | 타임라인 기획표 | `timeline.xlsx` 또는 `timeline.csv` 한 개 |
| ③ | 기획표 미리보기 | 파일명·구간·자막이 정상이면 `OK` 입력 |
| ④ | 미디어 | 기획표에 적힌 사진·영상 전부 |

별도 자막 설정을 켠 경우에만 ②와 ③ 사이에 [정밀 자막 Excel 양식](../templates/subtitles_template.xlsx) 또는 `subtitles.csv` 창이 하나 더 나타납니다. 첫 검사에서는 끄는 것을 권장합니다. 미리보기는 문구 확인용이며 정확한 Title 렌더링은 Final Cut 검사에서 확인합니다.

## 3. 통과 여부 확인

Colab 출력에 다음 내용이 보여야 합니다.

- `소스 방식: developer_starter_zip`
- 기획표의 모든 파일이 미디어와 연결됨
- 입력 최종 검사 통과
- 빌드와 상대경로 검사 완료
- `DevSmoke_FinalCut_Result.zip` 다운로드

결과 ZIP의 기본 구조:

~~~text
DevSmoke_FinalCut_Result.zip
├─ manifest.json
└─ Generated/
   ├─ vertical_9x16/
   │  ├─ DevSmoke_vertical_9x16_clean.fcpxml
   │  ├─ DevSmoke_vertical_9x16_with_titles.fcpxml
   │  ├─ DevSmoke_vertical_9x16.srt
   │  ├─ build_report.txt
   │  └─ .build_media/
   └─ horizontal_16x9/
      ├─ DevSmoke_horizontal_16x9_clean.fcpxml
      ├─ DevSmoke_horizontal_16x9_with_titles.fcpxml
      ├─ DevSmoke_horizontal_16x9.srt
      ├─ build_report.txt
      └─ .build_media/
~~~

원본 미디어와 `.py`, `.sh` 실행 파일은 결과 ZIP에 없어야 합니다.

## 4. 이 단계가 확인하지 않는 것

0단계는 Colab의 XML 생성만 확인합니다. 다음은 별도입니다.

- GitHub 공개 주소에서 소스를 내려받는 과정: 1단계 공개 후 확인
- Final Cut Pro 실제 가져오기와 내보내기: 기본 Mac 검사에서 확인

오류가 나면 `런타임 > 런타임 다시 시작` 후 처음부터 다시 올립니다. 해결되지 않으면 [문제 해결](TROUBLESHOOTING.md)에 따라 실행한 셀, 오류 전체와 비식별 테스트 기획표를 기록합니다.

통과했다면 [1단계 GitHub 공개](01_GITHUB_PUBLISH.md)로 이동합니다.
