# System Neo 60초 예제

첨부 스타터의 18개 장면, 세로 1080×1920·30fps 기획을 보존한 예제입니다. v0.6.0에서도 일반 영상 자막을 **Basic Title**로 만들고 SRT도 함께 생성하는 설정이 기본입니다.

저작권과 용량 때문에 촬영 원본과 BGM은 저장소에 포함하지 않습니다. 사용 권한이 있는 파일을 직접 넣습니다.

## 1. 필요한 폴더와 파일

~~~text
examples/system_neo/
├─ Media/
│  ├─ S01_event_hook.mp4
│  ├─ S02_event_scan.mp4
│  ├─ ...
│  └─ S18_company_end.mp4
├─ Docs/
│  └─ system_neo_대사표.csv
├─ Audio/
│  └─ neo_system_bed.m4a        # BGM을 쓸 때만
├─ timeline.csv
└─ project.json
~~~

빈 폴더:

~~~bash
mkdir -p \
  examples/system_neo/Media \
  examples/system_neo/Audio \
  examples/system_neo/Docs
~~~

timeline.csv에 적힌 18개 미디어 파일명과 실제 이름이 정확히 같아야 합니다.

대사표 최소 형식:

~~~csv
번호,시작,끝,최종 대사,장면 의도
S01,00:00:00.200,00:00:02.800,첫 번째 대사,오프닝
S02,00:00:03.100,00:00:05.800,두 번째 대사,스캔
~~~

## 2. 사진·영상과 CSV만 있을 때

BGM과 고급 스타일 없이 먼저 러프컷을 확인하려면 간편 모드를 사용합니다. Docs/system_neo_대사표.csv가 하나 있으면 자동 감지해 Title XML + SRT를 만듭니다.

~~~bash
python3 make_xml.py examples/system_neo --layout portrait --validate-only
python3 make_xml.py examples/system_neo --layout portrait
~~~

결과:

~~~text
examples/system_neo/Generated/
└─ vertical_9x16/
   ├─ system_neo_vertical_9x16_with_titles.fcpxml
   ├─ system_neo_vertical_9x16_clean.fcpxml
   ├─ system_neo_vertical_9x16.srt
   ├─ build_report.txt
   └─ .build_media/                 # 사진이 있을 때
~~~

간편 모드는 Apple SD Gothic Neo 등 일반 기본 스타일을 사용합니다. 정확한 System Neo 폰트·위치·role 설정이 필요하면 다음 고급 모드를 사용합니다.

## 3. System Neo 스타일로 만들기

project.json에는 다음 Title 설정이 들어 있습니다.

~~~json
"subtitles": {
  "file": "Docs/system_neo_대사표.csv",
  "mode": "title",
  "srt": true,
  "role": "System Neo",
  "font": "NeoDunggeunmo Code",
  "font_size": 44,
  "position_y": -720,
  "outline_width": -3,
  "shadow": true,
  "prefix": "system neo:"
}
~~~

- role: Final Cut 관리용 메타데이터이며 titles.System Neo로 정규화됩니다.
- font, font_size, position_y, outline, shadow: 화면 스타일입니다.
- prefix: CSV 대사 맨 앞에 이미 있는 `system neo:`를 감지해 별도 색으로 스타일링하는 기준입니다. 자동으로 문구를 추가하지 않으며 role과 별개입니다.

NeoDunggeunmo Code가 대상 Mac에 설치되어 있지 않으면 Final Cut에서 다른 폰트로 대체될 수 있습니다.

BGM 파일까지 있다면 그대로 실행합니다.

~~~bash
python3 csv_to_fcpxml.py \
  --config examples/system_neo/project.json \
  --validate-only

python3 csv_to_fcpxml.py \
  --config examples/system_neo/project.json
~~~

BGM이 없다면 project.json의 bgm 객체를 다음처럼 바꾼 뒤 실행합니다.

~~~json
"bgm": null
~~~

고급 `project.json` 결과의 공통 이름은 `output_basename`에 따라 `system_neo`가 됩니다. 이 고급 모드는 기존 설정과의 호환을 위해 `output_dir` 바로 아래에 평면 구조로 출력합니다.

~~~text
examples/system_neo/Generated/
├─ system_neo_with_titles.fcpxml   # 일반 영상용
├─ system_neo_clean.fcpxml
├─ system_neo.srt
└─ build_report.txt
~~~

접근성 Caption도 함께 필요하면 project.json에서 mode를 both로 바꿉니다.

~~~json
"mode": "both"
~~~

그러면 system_neo_with_captions.fcpxml도 생성됩니다.

## 4. Final Cut Pro에서 확인

1. FCPXML 1.14를 지원하는 Final Cut Pro 11.2 이상에서 File > Import > XML을 선택합니다.
2. 일반 영상은 `*_with_titles.fcpxml`을 가져옵니다.
3. Title의 시간, 대사, role, NeoDunggeunmo Code, 44 크기, Y 위치, 윤곽선과 그림자를 확인합니다.
4. 평소 File > Share로 짧게 내보내 Title이 보이는지 확인합니다.

Basic Title은 영상 그래픽이므로 별도 Caption 번인 설정 없이 기본 내보내기에 표시됩니다. Caption XML은 접근성·언어 선택용이고, SRT는 플랫폼 별도 업로드용입니다.

이 저장소의 XML 검사만으로 실제 Final Cut 렌더링을 보장할 수는 없습니다. GitHub 배포 전에는 대상 Mac의 Final Cut Pro 11.2 이상 또는 FCPXML 1.14를 지원하는 버전에서 Title import·편집·Share까지 확인합니다.

## 5. 경로 유지

path_mode는 relative입니다. Mac과 Colab 사이에서 옮길 때 Generated/만 떼어 놓지 말고 Media/, Audio/, Docs/, Generated/의 상대 위치를 유지합니다.

고급 출력도 기본적으로 examples/system_neo 프로젝트 폴더 안으로 제한됩니다. 외부 출력이 꼭 필요한 경우에만 위험과 경로를 확인한 뒤 --allow-external-output을 사용합니다.
