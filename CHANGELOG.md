# 변경 기록

## 0.6.2-rc1 · 블로그 공개 전 안정화 후보

기준 main: bd909983e191b32fddeb53d5f506274143511d91.

- 파일명·내용·표시 시간·해상도·화면 맞춤을 반영한 사진 캐시 식별값.
- 파일명 누락, 중복/알 수 없는 열, 열 개수 오류, 잘못된 시간·소리 입력 검증.
- 한글 NFC/NFD 파일명 대응 및 정규화 중복 방지.
- 임시 폴더에서 생성·검증 후 출력 교체. 실패 시 이전 XML 보존 및 다운로드 차단.
- 입력/출력 해시와 실행 식별값 검증. 이번에 사용한 파일만 ZIP에 포함.
- Colab 업로드 완료 확인, 세션 분리, 실행 코드 커밋 고정.
- CSV/XLSX 양식, README, 블로그 원고, 공개 전 확인표, 회귀 테스트 및 CI.
- Basic Title의 intrinsic adjustment를 text 요소 앞에 배치.

사용법 유지: 기본 6열, python run.py my-video --layout portrait --fit fit, 30fps, Basic Title.
실제 Colab 브라우저·Final Cut Pro·전체 Apple DTD 검증은 공개 전 수동 확인 대상입니다.
