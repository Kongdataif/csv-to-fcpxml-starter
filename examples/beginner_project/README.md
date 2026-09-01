# 초보자 혼합 미디어 예제

이 예제는 영상 2개와 사진 2개를 순서대로 이어 붙이는 기획표입니다. 저장소에는 개인 미디어를 포함하지 않으므로 `Media/README.md`를 보고 같은 이름의 테스트 파일을 준비하거나 CSV의 파일명을 자신의 파일명으로 바꾸세요.

## 1. 예제 선택

### 선택 1: 장면마다 자막 하나

`inline_titles/timeline.csv`를 사용합니다. `화면 자막`이 각 장면 전체 길이에 Basic Title과 SRT로 들어갑니다. 별도 `subtitles.csv`는 업로드하지 않습니다.

### 선택 2: 한 장면 안에서 자막 여러 개

1. `precise_titles/timeline.csv`를 Colab의 timeline CSV로 선택합니다.
2. 노트북 설정에서 `USE_SEPARATE_SUBTITLES_CSV = True`로 바꿉니다.
3. `precise_titles/subtitles.csv`를 두 번째 업로드 창에 올립니다.
4. 미디어 네 개를 올립니다.

인라인 `화면 자막`과 별도 `subtitles.csv`를 동시에 사용하면 중복을 추측할 수 없어 오류로 중단합니다.

## 2. 이 예제의 계산

다음 길이의 테스트 파일을 가정합니다.

| 파일 | 종류·원본 길이 | 사용할 구간 | 완성 타임라인 |
|---|---|---|---|
| `cafe_boot.mov` | 영상 18.4초 | 12~16초, 4초 | 00:00:00.000–00:00:04.000 |
| `ipad_drawing.png` | 사진 | 3초 | 00:00:04.000–00:00:07.000 |
| `office.mp4` | 영상 7.2초 | 전체 7.2초 | 00:00:07.000–00:00:14.200 |
| `ending.jpg` | 사진 | 2.5초 | 00:00:14.200–00:00:16.700 |

실제 영상 길이가 다르면 전체 사용 행의 최종 시간도 달라집니다. 별도 `subtitles.csv`의 마지막 시간이 실제 완성 길이를 넘지 않게 조절하세요.

## 3. Mac에서 실행 — 기본 경로

`examples/beginner_project/Media/`에 표의 네 파일을 넣은 뒤, 저장소 루트에서 선택한 기획표만 명시합니다.

장면마다 자막 하나:

```bash
python3 make_xml.py examples/beginner_project \
  --timeline inline_titles/timeline.csv \
  --layout both
```

한 장면에 정밀 자막 여러 개:

```bash
python3 make_xml.py examples/beginner_project \
  --timeline precise_titles/timeline.csv \
  --subtitles precise_titles/subtitles.csv \
  --layout both
```

결과는 `Generated/vertical_9x16/`과 `Generated/horizontal_16x9/`으로 나뉩니다. 원하는 방향의 `*_with_titles.fcpxml`을 Final Cut Pro의 `File > Import > XML`로 가져옵니다.

## 4. Colab에서 실행 — 선택 경로

1. 저장소 README의 **Google Colab에서 열기**를 누릅니다.
2. `런타임 > 모두 실행`을 선택합니다.
3. 위에서 고른 timeline CSV 하나를 올립니다.
4. 정밀 자막 선택일 때만 `subtitles.csv`를 올립니다.
5. Media의 사진·영상을 모두 올립니다.
6. 검사 요약을 확인하고 `프로젝트명_FinalCut_Result.zip`을 받습니다.

결과의 `Generated/`를 Mac에서 원본 `Media/` 옆에 놓은 뒤, 원하는 방향 폴더의 `*_with_titles.fcpxml`을 Final Cut Pro의 `File > Import > XML`에서 선택합니다.
