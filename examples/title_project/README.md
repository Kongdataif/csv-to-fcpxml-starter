# 화면 자막 Title 데모

`timeline.csv + subtitles.csv + Media/`만으로 일반 영상용 Basic Title FCPXML과 SRT를 만드는 최소 예제입니다.

저장소 루트에서 실행하세요.

```bash
bash scripts/run_title_demo.sh
```

스크립트가 작은 데모 미디어를 자동으로 만든 뒤 다음 결과를 검사합니다.

`run_title_demo.sh`는 이전 평면 출력과의 호환성을 확인하는 개발 데모입니다. 새 사용자 작업은 `make_xml.py <프로젝트> --layout portrait|landscape|both`를 사용하여 방향별 폴더로 출력하세요.

```text
examples/title_project/Generated/
├─ title_project_with_titles.fcpxml   # Final Cut에 먼저 가져올 파일
├─ title_project_clean.fcpxml         # 자막 없는 버전
├─ title_project.srt                  # 플랫폼 업로드용
└─ build_report.txt
```

Mac에서는 `title_project_with_titles.fcpxml`을 더블클릭하거나 Final Cut Pro의 `File > Import > XML`로 가져옵니다. Title은 일반 영상 그래픽이므로 별도의 Caption 번인 설정 없이 기본 영상 내보내기에 표시됩니다.

두 번째 자막은 2초의 장면 컷을 넘어가도록 일부러 구성되어 있습니다. Caption과 달리 Title 모드는 이 자막을 누락하지 않고 시작 장면에 연결한 채 전체 길이를 유지합니다.
