# 편집 프로그램과 XML 호환성

## 결론

이 프로젝트가 만드는 `.fcpxml`은 **Final Cut Pro용 FCPXML**입니다. 모든 영상 편집 프로그램이 공통으로 사용하는 하나의 XML 규격은 아닙니다.

따라서 다음처럼 이해하면 됩니다.

| 질문 | 답 |
|---|---|
| Final Cut Pro에서 사용할 수 있나요? | 이 프로젝트의 기본 대상입니다. |
| 다른 편집 프로그램도 XML을 쓰나요? | 일부 프로그램은 XML 가져오기·내보내기를 제공하지만 규격과 지원 범위가 다를 수 있습니다. |
| 확장자가 `.xml`이면 같은 파일인가요? | 아닙니다. XML 내부 구조와 버전이 달라 서로 호환되지 않을 수 있습니다. |
| 이 XML 안에 원본 영상이 들어 있나요? | 아닙니다. 파일 위치, 시간, 배치와 자막 같은 편집 정보를 기록합니다. |

## 현재 대상별 판단

| 대상 | 이 프로젝트의 `.fcpxml` | 주의 |
|---|---|---|
| Final Cut Pro | 공식 생성 대상 | [Apple의 XML 전송 안내](https://support.apple.com/guide/final-cut-pro/use-xml-to-transfer-projects-verdbd66ae/mac)대로 직접 import. 실제 사용하는 Final Cut 버전에서 렌더링 확인 |
| DaVinci Resolve 20 | FCPXML import 경로가 있으나 제한적 호환 | [Resolve 20 공식 매뉴얼](https://documents.blackmagicdesign.com/UserManuals/DaVinci_Resolve_20_Reference_Manual.pdf)은 FCPXML 가져오기를 설명하지만, Title은 Basic Text로 변환되고 일부 서식·효과만 전달됨. 이 프로젝트의 FCPXML 1.14 결과는 실제 검증 후 사용 |
| Adobe Premiere Pro | `.fcpxml` 직접 import 불가 | [Adobe 공식 안내](https://helpx.adobe.com/premiere/desktop/organize-media/import-files/migrate-from-final-cut-pro-x.html)에 따라 별도 변환 도구로 FCP 7 계열 XML을 만든 뒤 가져와야 하며, 일부 Title·효과가 손실될 수 있음 |

즉, 이번 GitHub 배포판은 Final Cut Pro용으로 안내합니다. Resolve용은 별도의 실험 기능으로 검증하기 전까지 지원 대상에 넣지 않고, Premiere용이라고 표기하지 않습니다.

## FCPXML이 담는 것

- 프로젝트 해상도와 FPS
- 사진·영상 파일 참조
- 장면 순서와 사용 구간
- 화면 맞춤
- 원본 오디오 포함 여부
- Basic Title 또는 Caption 정보

원본 사진·영상 자체는 XML 안에 복사되지 않습니다. 그래서 `Media`와 사진용 `.build_media`를 XML과 함께 유지해야 합니다.

## 다른 편집 프로그램으로 옮길 때

다른 프로그램에 `Import XML` 메뉴가 있더라도 다음 항목이 모두 보존된다고 가정하면 안 됩니다.

- 타이틀 글꼴·크기·위치
- Caption 역할과 언어
- 사진 캐시 연결
- 화면 맞춤과 Transform
- 복합 클립·효과·트랜지션
- 프로젝트 색 공간과 FPS

가져오기를 시험한다면 실제 작업의 복사본과 짧은 샘플을 사용하세요. 장면 순서뿐 아니라 타이틀, 오디오, 화면 맞춤과 미디어 재연결까지 확인해야 합니다.

## 이 프로젝트의 지원 범위

현재 자동 생성·검증 대상은 Final Cut Pro FCPXML입니다. 다른 편집기용 XML·프로젝트 파일을 같은 결과라고 보장하지 않습니다.

FCPXML 자체 구조와 버전은 [Apple FCPXML 개발자 참조](https://developer.apple.com/documentation/professional-video-applications/fcpxml-reference)를 기준으로 합니다. 여러 편집기 사이에서 자막 문구와 시간만 옮길 때는 앱 종속 Title보다 함께 생성되는 `.srt`가 더 안전합니다.

향후 다른 편집기를 정식 지원하려면 한 FCPXML을 억지로 공용 파일로 쓰기보다, 동일한 기획표에서 편집기별 출력 어댑터를 따로 만드는 구조가 안전합니다.

```text
timeline.xlsx + Media/
        ├─ Final Cut Pro용 FCPXML
        ├─ 다른 편집기용 교환 형식
        └─ 검토용 EDL·자막 등
```

각 출력은 대상 프로그램에서 별도로 검증해야 합니다.
