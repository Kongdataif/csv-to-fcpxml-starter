# 세로·가로 동시 출력 예제

이 예제는 기본 6열에 방향별 화면 맞춤 열을 선택적으로 추가한 모습입니다.
GitHub에서 [`timeline.csv`](timeline.csv)를 먼저 표처럼 확인한 뒤, 실제로
실행할 때는 `Media/README.md` 대신 기획표와 이름이 같은 사진·영상을
`Media/`에 넣습니다.

Excel이나 Numbers에서 작성하려면 [`multi_format_timeline.xlsx`](../../templates/multi_format_timeline.xlsx)를 복사해 `timeline.xlsx`로 이름을 바꾸세요. Numbers에서는 편집을 마친 뒤 Excel 형식으로 내보냅니다.

```bash
python make_xml.py examples/multi_format --layout both --validate-only
python make_xml.py examples/multi_format --layout both
```

`세로 화면 맞춤` 또는 `가로 화면 맞춤`이 비어 있으면 공통 `화면 맞춤`을
사용합니다. 장면 순서·길이·자막 자체가 세로와 가로에서 다르다면 이 열을 더
늘리지 말고 기획표를 두 개로 나누는 편이 좋습니다.
