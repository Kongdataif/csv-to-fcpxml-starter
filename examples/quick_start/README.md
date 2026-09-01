# 처음 보는 6열 예제

**[timeline.csv](timeline.csv)**를 누르면 GitHub에서 표로 미리 볼 수 있습니다. 세 행은 차례대로 “영상 전체 → 사진 3초 → 영상의 1~4초 구간”을 뜻합니다.

실제 작성은 [Excel·Numbers용 작성 예시 양식](../../templates/simple_timeline.xlsx)을 권장합니다. 예시 행을 자신의 작업으로 바꾸면 되고, `.xlsx`를 Mac 로컬이나 Colab에서 그대로 사용할 수 있습니다.

배포본 CSV에는 Excel용 UTF-8 표시가 들어 있습니다. 그래도 한글이 깨져 보이면 저장하지 말고 파일을 다시 받은 뒤 `CSV UTF-8`로 저장하세요.

| CSV 파일명 | 준비할 실제 파일 | 사용 방식 |
|---|---|---|
| `intro.mp4` | 같은 이름의 영상 | 영상 전체, 원본 소리 사용 |
| `photo.jpg` | 같은 이름의 사진 | 3초 표시, 소리 없음 |
| `outro.mov` | 같은 이름의 영상 | 원본 1~4초, 원본 소리 끄기 |

## 내 파일로 바꾸기

1. [Excel·Numbers용 작성 예시 양식](../../templates/simple_timeline.xlsx)을 엽니다.
2. `파일` 열을 확장자까지 포함한 내 사진·영상 파일명으로 바꿉니다.
3. 필요 없는 예시 행은 지우고 장면 순서대로 행을 추가합니다.
4. Excel은 `.xlsx`를 그대로 저장합니다. Numbers는 `파일 > 다음으로 내보내기 > Excel`로 `.xlsx`를 만듭니다.
5. `.numbers` 원본은 직접 사용하지 말고 `.xlsx`로 내보냅니다.
6. Mac은 프로젝트의 `Media/`에, Colab은 미디어 업로드 창에 기획표에 적은 사진·영상을 모두 넣습니다.

파일명은 대소문자까지 실제 파일과 같아야 합니다. 사진 행은 영상 시작·끝을 비우고, 영상 행은 사진 표시 시간을 비우세요.

## Mac에서 실행 — 기본 경로

이 예제의 `timeline.csv`를 그대로 쓰거나, 그 파일을 지우고 같은 폴더에 `timeline.xlsx`를 넣습니다. 둘 다 두면 자동으로 고르지 않으므로 `--timeline timeline.xlsx`처럼 하나를 명시해야 합니다. `Media/`에 `intro.mp4`, `photo.jpg`, `outro.mov`를 넣고 저장소 루트에서 실행합니다.

```bash
python3 make_xml.py examples/quick_start --layout both --validate-only
python3 make_xml.py examples/quick_start --layout both --preview-only
python3 make_xml.py examples/quick_start --layout both
```

실행 전에 [Mac 로컬 실행 가이드](../../docs/MAC.md)의 1회 설치를 먼저 완료하세요. 설치 없이 짧게 확인하려면 [Colab 안내](../../docs/02_BEGINNER_COLAB.md)를 선택할 수 있습니다.
