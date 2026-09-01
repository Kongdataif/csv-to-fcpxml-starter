# 입력 파일 작성법

이 문서는 정밀 CSV, `project.json`, BGM과 스타일 설정까지 다루는 입력 참조입니다. 처음 사용하는 사람은 더 짧은 [사용자 가이드](USER_GUIDE.md)부터 시작하세요.

새 사용자는 **초보자 순서 누적형 `timeline.xlsx`**를 사용하면 됩니다. 사진인지 영상인지, Final Cut 타임라인의 시작·끝, dB 음량을 계산할 필요가 없습니다. 공개 Colab은 동일한 6열의 `.xlsx`와 UTF-8 `.csv`를 모두 받습니다.

| 입력 방식 | 누가 사용하나요? | 사용자가 결정하는 것 | 타임라인 배치 |
|---|---|---|---|
| 초보자 순서 누적형 | 처음 쓰는 사용자, 반복 양식의 러프컷 | 영상 원본 구간, 사진 시간, 자막, 소리 | 기획표 행을 앞 장면 뒤에 자동 누적 |
| 정밀/고급 타임라인 | 방송 타임코드, gap, 기존 기획표 | 완성 타임라인 위치까지 직접 지정 | `timeline_in/out` 그대로 |
| `project.json` 고급 모드 | BGM·스타일·출력 규격을 고정할 개발자 | 모든 생성 설정 | 정밀 CSV 사용 |

Mac 간편 CLI와 Colab은 초보자 `.xlsx`/`.csv`를 같은 내부 CSV로 정규화해 엔진에 전달합니다. `project.json`을 직접 사용하는 고급 core 모드는 정밀 CSV를 입력으로 사용합니다.

## 공통 파일 형식·파일명 규칙

- 공개 Colab: 제공된 `.xlsx` 양식을 그대로 올리거나 UTF-8/UTF-8 BOM `.csv`를 올립니다.
- Excel: [타임라인 `.xlsx` 양식](../templates/simple_timeline.xlsx)을 편집해 그대로 저장합니다.
- Numbers: `.xlsx` 양식을 열어 편집한 뒤 `파일 > 다음으로 내보내기 > Excel`로 저장합니다. `.numbers` 원본은 직접 업로드하지 않습니다.
- CSV: Excel은 `CSV UTF-8(쉼표로 분리)`, Numbers는 텍스트 인코딩 `Unicode(UTF-8)`로 내보냅니다. CP949/EUC-KR은 지원하지 않습니다.
- Mac 간편 CLI: `.xlsx` 또는 UTF-8 `.csv`를 직접 선택합니다. 같은 폴더에 두 형식이 모두 있으면 `--timeline`으로 하나를 명시합니다.
- 초보자 기획표의 `파일`에는 폴더 경로 없이 실제 파일명만 적습니다.
- 파일명은 확장자와 대소문자까지 실제 업로드와 같아야 합니다.
- `/`, `\`, `..`, `C:\...`, `/Users/...`, `/content/...` 같은 경로는 초보자 `파일`에 쓰지 않습니다.
- 같은 이름의 미디어를 두 개 올리지 않습니다. Colab 직접 업로드는 대소문자와 Unicode NFC 정규화 후 같아지는 파일이 여러 개면 충돌로 거부하며 CSV와 실제 이름의 정확한 일치를 요구합니다. Mac 로컬 어댑터는 정확한 이름이 없고 NFC/NFD 표현만 다른 후보가 유일할 때만 자동 연결하고 경고합니다.
- 셀 안에 쉼표가 있으면 CSV 프로그램이 자동으로 큰따옴표로 감싸도록 합니다. CSV를 메모장에서 직접 편집할 때는 `"쉼표가 있는 문장"`처럼 씁니다.
- `.xls`, `.xlsm`, `.numbers`는 공개 Colab 직접 입력이 아닙니다. `.xlsx` 또는 UTF-8 `.csv`로 저장해 올립니다.

## 시간 입력 형식

권장 형식은 `HH:MM:SS.mmm`입니다.

~~~text
00:00:12.000   # 12초
00:01:02.500   # 1분 2.5초
01:02:03.250   # 1시간 2분 3.25초
~~~

다음 형식도 읽습니다.

- `SS` 또는 `SS.sss`: 초
- `MM:SS.sss`: 분:초
- `HH:MM:SS.sss`: 시:분:초

음수 시간, `HH:MM:SS:FF` 프레임 표기와 FCPXML 내부의 `300/30s` rational 표기는 CSV 입력으로 지원하지 않습니다. 영상 원본 시작·끝은 확인한 원본 fps 프레임에 먼저 맞추고, 그 사용 길이는 프로젝트 fps의 정수 프레임으로 half-up 보정하여 누적합니다. 사진 시간도 프로젝트 fps 프레임으로 보정합니다. 29.97은 `30000/1001`, 23.976은 `24000/1001`, 59.94는 `60000/1001`로 정확히 처리하며 보정이 발생하면 검사 경고에 표시합니다.

## 초보자 순서 누적형 timeline.xlsx / timeline.csv

처음에는 [templates/simple_timeline.xlsx](../templates/simple_timeline.xlsx)의 기본 6열을 그대로 사용합니다. CSV가 필요하면 [templates/simple_timeline.csv](../templates/simple_timeline.csv)를 사용합니다.

~~~csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리
cafe_boot.mov,00:00:12.000,00:00:16.000,,카페에서 첫 부팅,사용
ipad_drawing.png,,,3,아이패드로 그린 그림,
office.mp4,,,,회사에서도 이어서 사용,끄기
~~~

기본 6열에서 장면 순서는 기획표에 보이는 행 순서입니다. 필요할 때만 `순서`, `화면 맞춤`, `세로 화면 맞춤`, `가로 화면 맞춤`, `메모`를 추가합니다.

~~~csv
순서,파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리,화면 맞춤,메모
1,cafe_boot.mov,00:00:12.000,00:00:16.000,,카페에서 첫 부팅,사용,화면 채우기,원본 12~16초
2,ipad_drawing.png,,,3,아이패드로 그린 그림,,전체 보이기,사진 장면
~~~

### 사진·영상 종류는 자동 판별합니다

사용자는 `종류` 열을 만들지 않습니다. 도구가 파일 확장자와 실제 스트림 정보를 확인합니다.

| 업로드 | 1차 판별 | 추가 확인 |
|---|---|---|
| `.mov`, `.mp4`, `.m4v` 등 | 영상 | `ffprobe`로 영상 길이·해상도·fps·오디오 유무 확인 |
| `.jpg`, `.jpeg`, `.png`, `.heic`, `.tif` 등 | 사진 | 사진으로 배치하고 필요하면 `ffmpeg`로 캐시 영상 생성 |
| `.m4a`, `.mp3` 등 오디오만 | 장면 미디어로 불가 | BGM 고급 설정에서만 사용 |
| 알 수 없는 확장자·실제 미디어가 아닌 파일 | 오류 | 임의로 영상이나 사진으로 추측하지 않음 |

확장자만 `.mov`로 바꾼 파일을 정상 영상으로 믿지 않습니다. 영상 행은 실제 영상 스트림과 재생 길이가 있어야 합니다. Final Cut의 코덱 지원 범위는 FFmpeg와 다를 수 있으므로 MOV/MP4라도 대상 Mac에서 재생 가능한지 확인하세요.

### 기본 열과 선택 열의 정확한 의미

#### `순서` — 선택

- 의미: 완성 영상에 장면을 놓을 순서입니다.
- 권장 입력: `1`, `2`, `3`처럼 1 이상의 중복 없는 정수입니다.
- `순서` 열이 있으면 모든 사용 행에 값이 있어야 하며 빈칸, `0`, 음수, `1.5`, 중복은 오류입니다.
- `순서` 열 자체를 생략한 이전 초보자 파일은 CSV에 보이는 행 순서를 사용합니다.
- 열을 생략하면 CSV에 보이는 행 순서를 사용합니다.

#### `파일`

- 의미: Colab에 업로드하거나 로컬 `Media/` 안에 둔 실제 사진·영상 파일명입니다.
- 필수이며 빈칸 기본값은 없습니다.
- `cafe_boot.mov`처럼 확장자를 포함합니다.
- `Media/cafe_boot.mov`, `C:\Video\cafe_boot.mov`, `/Users/me/cafe_boot.mov`는 초보자 형식에서 오류입니다.
- 같은 파일을 여러 행에서 다른 구간으로 재사용할 수 있습니다. `순서`는 각 행마다 달라야 합니다.

#### `영상 원본 시작`

- 의미: 원본 영상 내부에서 가져오기 시작할 지점입니다.
- 영상에서 `영상 원본 끝`과 함께 입력하면 트림합니다.
- 시작·끝이 모두 빈칸이면 영상 처음부터 끝까지 사용합니다.
- 한쪽만 입력하면 도구가 나머지를 추측하지 않고 오류를 냅니다.
- 사진에 입력하면 오류입니다.

#### `영상 원본 끝`

- 의미: 원본 영상 내부에서 가져오기를 멈출 지점입니다.
- 시작보다 뒤여야 하고 실제 영상 길이를 넘을 수 없습니다.
- 시작·끝 차이가 이 장면의 완성 타임라인 길이가 됩니다.
- 자동 리타이밍은 하지 않습니다.

예:

~~~text
원본 영상 길이: 00:00:18.400
영상 원본 시작: 00:00:12.000
영상 원본 끝:   00:00:16.000
사용 길이:      4초
~~~

#### `사진 표시 시간(초)`

- 의미: 정지 사진을 완성 영상에서 몇 초 보여줄지 정합니다.
- 사진에서 빈칸이면 Colab 설정의 기본값을 사용하며 기본은 3초입니다.
- `3`, `2.5`, `0.75`처럼 0보다 큰 초를 입력합니다.
- `0`, 음수, 글자 또는 프레임 보정 후 0이 되는 지나치게 짧은 값은 오류입니다.
- 영상 행에 입력하면 오류입니다. 영상 속도를 늘이거나 줄이는 입력이 아닙니다.

#### `화면 자막`

- 의미: 그 장면의 처음부터 끝까지 보일 Basic Title 한 개입니다.
- 빈칸이면 해당 장면의 인라인 자막을 만들지 않습니다.
- 줄바꿈이 필요하면 셀에 문자 `\n`을 넣을 수 있습니다.
- 인라인 자막은 Basic Title XML과 SRT 모두에 반영됩니다.
- 한 장면 안에서 자막이 여러 번 바뀌면 이 열을 비우고 별도 `subtitles.xlsx` 또는 `subtitles.csv`를 사용합니다.
- 인라인 자막과 별도 자막 기획표를 동시에 사용하면 중복을 추측하지 않고 오류로 중단합니다. 둘 중 하나만 선택합니다.

#### `소리`

- 의미: 영상 원본의 오디오 스트림을 타임라인에 포함할지 정합니다.
- 빈칸 또는 `사용`: 원본 소리를 포함합니다.
- `끄기`: 원본 소리를 포함하지 않습니다.
- 친화 별칭 `켜기`, `원본`, `원본 소리`, `예`, `음소거`, `아니오`와 영문 true/false도 읽지만 새 CSV에는 `사용`/`끄기`를 권장합니다.
- 사진에는 오디오가 없으므로 빈칸을 권장합니다. 값을 쓰면 무시하고 보고서에 경고를 남깁니다.
- 영상 자체에 오디오 스트림이 없으면 `사용`이어도 소리가 생기지 않으며 경고가 표시됩니다.
- 초보자 모드의 내부 음량은 원본 레벨인 `0 dB`이며 사용자가 dB를 입력하지 않습니다.

#### `화면 맞춤` — 선택

| 입력 | 내부 conform | 의미 | 주의 |
|---|---|---|---|
| 빈칸, `전체 보이기`, `전체 보기`, `fit` | `fit` | 원본 전체가 보이도록 맞춤 | 비율이 다르면 여백 가능 |
| `화면 채우기`, `채우기`, `fill` | `fill` | 프레임을 꽉 채움 | 가장자리 일부 크롭 가능 |
| `자동 맞춤 안 함`, `맞춤 안 함`, `원본`, `none` | `none` | 영상에서 Final Cut 자동 conform을 끔 | 사진 캐시는 안전한 `fit`으로 처리 |

사진 캐시 모드에서는 `none`도 기술적 안전을 위해 `fit` 즉 `전체 보이기`로 정규화합니다. 사진에 `자동 맞춤 안 함`을 적어도 원본 크기 그대로 배치되는 뜻이 아닙니다. 초보자는 중요한 내용이 잘리지 않는 `전체 보이기`를 권장합니다.

#### `세로 화면 맞춤`·`가로 화면 맞춤` — 선택

`--layout both`를 사용할 때 방향별로 다른 화면 맞춤을 주고 싶은 경우만 추가합니다. 값은 공통 `화면 맞춤`과 동일합니다.

- 세로 결과: `세로 화면 맞춤` → 빈칸이면 `화면 맞춤` → 둘 다 없으면 `전체 보이기`
- 가로 결과: `가로 화면 맞춤` → 빈칸이면 `화면 맞춤` → 둘 다 없으면 `전체 보이기`

```csv
파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리,화면 맞춤,세로 화면 맞춤,가로 화면 맞춤
interview.mov,,,,인터뷰,사용,전체 보이기,화면 채우기,전체 보이기
```

#### `메모` — 선택

- 의미: 장면 의도, 후속 편집 지시, 촬영 메모입니다.
- 빈칸이어도 생성 결과에 영향이 없습니다.
- 영상 화면에는 표시되지 않습니다.
- 변환 과정과 `build_report.txt`, 인라인 자막의 의도 필드에 남겨 디버깅에 도움을 줍니다.

### 헤더를 바꿔도 되나요?

초보자 형식에서는 제공된 한국어 헤더를 그대로 사용하세요. `파일`은 필수이며, `타임라인 시작`/`타임라인 끝` 또는 기존 `시작`/`끝` 열이 함께 있으면 정밀 형식으로 판별합니다. 알 수 없는 사용자 정의 열은 오타를 조용히 무시하지 않고 오류로 표시합니다.

기본 6열을 권장합니다. 숫자 순서, 공통·방향별 화면 맞춤 또는 편집 메모가 필요할 때만 `순서`, `화면 맞춤`, `세로 화면 맞춤`, `가로 화면 맞춤`, `메모` 열을 추가합니다. 선택 열도 제공된 이름을 그대로 사용합니다.

### 행을 앞에서부터 누적하는 방식

`순서` 열이 있으면 숫자로 정렬하고, 없으면 CSV 행 순서를 사용합니다. 각 행의 길이를 계산한 다음 cursor를 앞에서부터 누적합니다.

~~~text
첫 행 시작 = 0초
첫 행 끝   = 첫 행 시작 + 첫 행 길이
둘째 시작  = 첫 행 끝
둘째 끝    = 둘째 시작 + 둘째 길이
...
~~~

영상 전체 사용 시 `ffprobe`에서 읽은 실제 길이를, 트림 영상은 `원본 끝 - 원본 시작`을, 사진은 입력 초 또는 기본 3초를 사용합니다. 내부에서는 `Fraction`으로 누적하여 이진 부동소수점 오차를 피하고 최대 9자리 소수로 정밀 CSV에 전달한 뒤 프로젝트 프레임 경계로 보정합니다.

### 혼합 미디어 전체 예제

미디어 분석 결과:

| 파일 | 자동 판별 | 원본 정보 |
|---|---|---|
| `cafe_boot.mov` | 영상 | 18.4초, 오디오 있음 |
| `ipad_drawing.png` | 사진 | 2048×2732 |
| `office.mp4` | 영상 | 7.2초, 오디오 있음 |
| `ending.jpg` | 사진 | 1920×1080 |

작성 CSV:

~~~csv
순서,파일,영상 원본 시작,영상 원본 끝,사진 표시 시간(초),화면 자막,소리,화면 맞춤,메모
1,cafe_boot.mov,00:00:12.000,00:00:16.000,,카페에서 첫 부팅,사용,화면 채우기,원본 중 4초
2,ipad_drawing.png,,,3,아이패드로 그림 작업,,전체 보이기,기본 3초
3,office.mp4,,,,회사에서도 이어서 사용,끄기,화면 채우기,전체 영상 7.2초
4,ending.jpg,,,2.5,다음 편에 계속,,전체 보이기,엔딩 2.5초
~~~

계산 결과:

| 순서 | 사용할 원본 | 장면 길이 | 완성 타임라인 | 소리 | 자막 범위 |
|---:|---|---:|---|---|---|
| 1 | 영상 12~16초 | 4초 | 00:00:00.000–00:00:04.000 | 사용 | 장면 전체 4초 |
| 2 | 사진 | 3초 | 00:00:04.000–00:00:07.000 | 해당 없음 | 장면 전체 3초 |
| 3 | 영상 전체 | 7.2초 | 00:00:07.000–00:00:14.200 | 끄기 | 장면 전체 7.2초 |
| 4 | 사진 | 2.5초 | 00:00:14.200–00:00:16.700 | 해당 없음 | 장면 전체 2.5초 |

프레임률에 따라 표시 시간이 가장 가까운 프레임으로 소폭 보정될 수 있습니다.

## 별도 subtitles.xlsx / subtitles.csv

Mac 간편 CLI와 Colab 모두 [templates/subtitles_template.xlsx](../templates/subtitles_template.xlsx)를 사용할 수 있습니다. CSV가 필요하면 [templates/subtitles_template.csv](../templates/subtitles_template.csv)를 사용합니다.

~~~csv
번호,시작,끝,최종 대사,장면 의도
S01,00:00:00.200,00:00:01.800,드디어 맥북을 켰다,첫 장면 전반
S02,00:00:02.000,00:00:03.800,그런데 생각보다 어렵다,첫 장면 후반
~~~

| 열 | 필수 | 의미 |
|---|:---:|---|
| `id`/`번호` | 권장 | 자막 고유 ID |
| `start`/`시작` | 필수 | 완성 타임라인에서 자막 시작 |
| `end`/`끝` | 필수 | 완성 타임라인에서 자막 끝 |
| `text`/`최종 대사` | 필수 | 화면에 보일 글자, 문자 `\n`은 줄바꿈 |
| `notes`/`장면 의도` | 선택 | 생성 보고용 메모 |

Mac 로컬 정밀 엔진은 기존 영문 헤더 `id,start,end,text,notes`도 계속 읽습니다. 공개 Colab은 초보자 경험을 고정하기 위해 위 한국어 5개 헤더와 순서를 정확히 요구합니다.

자막 시간은 원본 영상 시간이 아니라 모든 장면을 이어 붙인 **완성 타임라인 시간**입니다. 같은 role/lane의 자막이 겹치면 오류입니다.

- Title 모드: 시작 시각의 primary clip 또는 gap에 Basic Title을 연결합니다. 끝이 다음 컷을 지나도 전체 길이를 유지할 수 있습니다.
- Caption 모드: 현재 한 primary clip 안에 완전히 들어가는 행만 연결합니다. 컷 경계를 넘거나 gap에 있는 Caption은 제외되고 보고서에 경고가 남습니다.
- SRT: 모든 정상 자막을 별도 파일로 기록합니다. 폰트·색·위치·role은 SRT에 저장되지 않습니다.

초보자 인라인 `화면 자막`과 별도 `subtitles.xlsx`/`subtitles.csv`는 동시에 사용하지 않습니다. Colab은 명시적 오류로 중단하므로 인라인 열을 모두 비우거나 별도 업로드 설정을 끕니다.

## 정밀/고급 타임라인 형식

### 기존 `파일,시작,끝`의 정확한 뜻

v0.3 이하의 간편 CSV를 계속 읽습니다.

~~~csv
파일,시작,끝
intro.mov,00:00:00.000,00:00:04.000
photo.png,00:00:04.000,00:00:07.000
~~~

여기서 `시작`과 `끝`은 **원본 영상 안에서 자를 시간**이 아닙니다.

| 열 | 의미 |
|---|---|
| `파일` | 실제 미디어 파일 |
| `시작` | 완성될 Final Cut 타임라인에서 클립을 놓기 시작할 위치 |
| `끝` | 완성될 Final Cut 타임라인에서 클립을 놓기 끝낼 위치 |

행 순서보다 `시작`/`끝` 값이 실제 위치를 결정합니다. 사이가 비면 gap이 생기고 두 primary clip이 겹치면 오류입니다. 원본 영상 트림은 별도 `원본 시작`/`원본 끝`을 씁니다.

### 정밀 전체 형식

~~~csv
id,kind,file,timeline_in,timeline_out,source_in,source_out,conform,include_audio,volume_db,notes,enabled
V01,video,intro.mov,00:00:00.000,00:00:04.000,00:00:12.000,00:00:16.000,fill,true,-3,원본 12초부터 4초,true
I01,image,photo.png,00:00:04.000,00:00:07.000,,,fit,false,0,사진 3초,true
~~~

| 열 | 필수 | 의미 |
|---|:---:|---|
| `id` | 권장 | 행 고유 ID, 중복 불가 |
| `kind` | 선택 | `video` 또는 `image`, 비우면 확장자로 추론 |
| `file` | 필수 | 간편 CLI는 Media의 파일명, project.json은 프로젝트 기준 상대경로 |
| `timeline_in` | 필수 | 완성 타임라인 시작 |
| `timeline_out` | 필수 | 완성 타임라인 끝 |
| `source_in` | 영상 선택 | 원본 시작, 기본 0 |
| `source_out` | 영상 선택 | 원본 끝, 기본 source_in + 타임라인 길이 |
| `conform` | 선택 | `fit`, `fill`, `none`, 기본 `fit` |
| `include_audio` | 선택 | 영상 원본 오디오 포함 여부 |
| `volume_db` | 선택 | 원본 레벨 대비 dB, 기본 0 |
| `notes` | 선택 | `build_report.txt`에 남는 메모 |
| `enabled` | 선택 | false면 행 제외 |

정밀 규칙:

- 주 스토리라인 영상·사진은 서로 겹칠 수 없습니다.
- 빈 구간은 gap으로 생성합니다.
- 영상의 `source_out - source_in`과 `timeline_out - timeline_in`은 같아야 합니다.
- 자동 retime/timeMap은 만들지 않습니다.
- 사진은 source 구간을 비우고 timeline 길이만큼 표시합니다.
- 영상 source 시간은 확인 가능한 원본 fps 프레임, 타임라인 시간은 프로젝트 fps 프레임으로 보정합니다.
- `volume_db = 0`은 무음이 아니라 원본 레벨, `-6`은 원본보다 6dB 감소입니다. 초보자 입력에는 이 열이 없습니다.

한국어 별칭 `번호`, `종류`, `파일`, `타임라인 시작`, `타임라인 끝`, `시작`, `끝`, `원본 시작`, `원본 끝`, `맞춤`, `원본 오디오`, `음량 dB`, `장면 의도`도 읽습니다.

## project.json 고급 모드

~~~json
{
  "event_name": "CSV Automation",
  "project_name": "My Rough Cut",
  "output_basename": "my_roughcut",
  "fcpxml_version": "1.14",
  "width": 1080,
  "height": 1920,
  "fps": "30",
  "color_space": "1-1-1 (Rec. 709)",
  "audio_rate": "48k",
  "timeline_csv": "timeline.csv",
  "output_dir": "Generated",
  "path_mode": "relative",
  "image_mode": "video-cache",
  "image_background": "#000000",
  "bgm": null,
  "subtitles": {},
  "captions": {}
}
~~~

| 키 | 기본/예 | 의미 |
|---|---|---|
| `event_name` | CSV Automation | Final Cut Event 이름 |
| `project_name` | CSV Rough Cut | Final Cut Project 이름 |
| `output_basename` | auto_roughcut | 생성 파일 공통 이름 |
| `fcpxml_version` | 1.14 | 생성 FCPXML 버전 |
| `width`, `height` | 1080, 1920 | 프로젝트 픽셀 크기, cache 모드는 짝수 |
| `fps` | 30 | fps 또는 rational 문자열 |
| `color_space` | Rec. 709 | 프로젝트 색공간 |
| `audio_rate` | 48k | sequence 오디오 샘플률 |
| `timeline_csv` | timeline.csv | 정밀 타임라인 CSV |
| `output_dir` | Generated | 프로젝트 안 결과 폴더 |
| `path_mode` | relative | 이동 가능한 상대경로 권장 |
| `image_mode` | video-cache | 사진을 MP4 캐시로 변환, `direct`는 실험적 |
| `image_background` | #000000 | fit 사진 여백 색상 |
| `bgm` | null | 선택 BGM 설정 |
| `subtitles` | {} | Title·Caption·SRT 새 설정 |
| `captions` | {} | v0.2 이하 호환, 새 프로젝트는 비움 |

v0.6.0 emitter는 FCPXML 1.14만 생성하고 Final Cut Pro 11.2 이상과 이후 호환 버전을 대상으로 합니다. FCPXML 1.14는 Final Cut Pro 11.2에서 도입됐습니다. 숫자만 낮춘다고 요소가 자동 다운그레이드되지 않으므로 다른 FCPXML 버전은 오류로 중단합니다. [Apple Final Cut Pro 릴리스 노트](https://support.apple.com/102825)

## subtitles 고급 설정

일반 영상용 권장 예:

~~~json
"subtitles": {
  "file": "Docs/subtitles.csv",
  "mode": "title",
  "srt": true,
  "role": "Subtitles",
  "font": "Apple SD Gothic Neo",
  "font_size": 44,
  "font_face": "Regular",
  "position_x": 0,
  "position_y": -720,
  "alignment": "center",
  "outline_color": "0 0 0 1",
  "outline_width": -3,
  "shadow": true,
  "shadow_color": "0 0 0 0.75",
  "shadow_offset": "2 -2",
  "shadow_blur_radius": 3,
  "prefix": "",
  "wrap_width": 20,
  "prefix_color": "0.447059 0.945098 1 1",
  "body_color": "1 1 1 1",
  "format": "ITT",
  "language": "ko-KR",
  "placement": "bottom"
}
~~~

### 출력 모드

| `mode` | 결과 |
|---|---|
| `title` | clean XML + Basic Title XML + 선택 SRT, 기본 추천 |
| `caption` | clean XML + iTT Caption XML + 선택 SRT |
| `both` | clean XML + Title XML + Caption XML + 선택 SRT |
| `off` | clean XML + 선택 SRT |

`srt` 기본값은 true입니다. 자막 기능 전체를 끄려면 빈 객체 또는 CLI `--no-subtitles`를 사용합니다.

### 역할·스타일·접두사는 서로 다릅니다

- `role`: Final Cut에서 타이틀을 분류하는 메타데이터입니다. `System Neo`는 `titles.System Neo`로 정규화됩니다.
- `font`, `font_size`, `position`, `alignment`, `outline`, `shadow`: 화면에 보이는 스타일입니다.
- `prefix`/`speaker_label`: CSV 대사 맨 앞에 **이미 있는** 문자열을 감지해 별도 스타일링하는 기준입니다. 문자열을 자동 추가하지 않습니다.

### 주요 Title 키

| 키 | 기본값 | 의미 |
|---|---|---|
| `font` | Apple SD Gothic Neo | 대상 Mac에 설치된 폰트 이름 |
| `font_size` | 44 | Title 글자 크기 |
| `font_face` | Regular | 폰트 face |
| `position_x`, `position_y` | 0, 화면 높이 -37.5% | 픽셀 기준 이동, 1920 높이에서 y=-720 |
| `position_x_percent`, `position_y_percent` | 없음 | 같은 축 픽셀 설정보다 우선하는 FCP 퍼센트 |
| `alignment` | center | left, center, right, justified |
| `outline_color`, `outline_width` | 검정, -3 | RGBA와 stroke 폭 |
| `shadow` 및 shadow 키 | true | 그림자 사용·색·offset·blur |
| `prefix_color`, `body_color` | 하늘색, 흰색 | 접두사/본문 RGBA |
| `bold` | false | 굵게 |
| `title_effect_uid` | Basic Title UID | 고급 Motion Title 참조, 보통 변경하지 않음 |

색은 `R G B A` 네 숫자이며 각 값은 0~1입니다. 폰트는 XML에 이름만 기록되며 자동 설치하거나 결과에 포함하지 않습니다.

### Caption·SRT 키

| 키 | 기본값 | 의미 |
|---|---|---|
| `format` | ITT | 현재 Caption XML 형식 |
| `language` | ko-KR | Caption 언어 |
| `placement` | bottom | top 또는 bottom |
| `wrap_width` | 20 | SRT 줄바꿈 기준, 8 이상 |
| `background_color` | 0 0 0 0.9 | Caption 배경 RGBA |

SRT에는 폰트, 색상, 위치와 role이 저장되지 않습니다.

## System Neo 예제

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
  "prefix": "system neo:",
  "wrap_width": 18
}
~~~

일반 영상은 `system_neo_with_titles.fcpxml`을 먼저 가져옵니다. `role`은 관리용, 폰트·위치·윤곽선·그림자는 화면 스타일, `prefix`는 CSV에 이미 있는 접두사 감지 기준입니다.

## 기존 captions 설정 호환

v0.2 이하의 설정도 계속 읽습니다.

~~~json
"captions": {
  "file": "Docs/captions.csv",
  "embed": true,
  "format": "ITT",
  "role": "System Neo",
  "language": "ko-KR",
  "placement": "bottom",
  "prefix": "system neo:",
  "wrap_width": 18
}
~~~

- `embed: true` → Caption XML + SRT
- `embed: false` → SRT만
- 새 `subtitles`와 기존 `captions`를 동시에 활성화 → 오류

새 프로젝트는 `subtitles`를 사용합니다. 기존 Caption을 일반 Title로 바꾸려면 키 이름을 `subtitles`로 바꾸고 `mode: "title"`, `srt: true`와 화면 스타일을 설정합니다.

## BGM 고급 설정

~~~json
"bgm": {
  "file": "Audio/bgm.m4a",
  "timeline_start": "00:00:03.000",
  "source_in": "00:00:10.000",
  "duration": "00:00:20.000",
  "volume_db": -18,
  "role": "music"
}
~~~

| 키 | 의미 |
|---|---|
| `file` | 프로젝트 기준 BGM 파일 |
| `timeline_start` | 완성 타임라인에서 BGM 시작 |
| `source_in` | 원본 오디오를 읽기 시작할 위치 |
| `duration` | 사용할 길이 |
| `timeline_end` | duration 대신 사용할 타임라인 끝 |
| `volume_db` | 원본 대비 음량 조절 |
| `role` | Final Cut audio role |

기존 `start`, `end`도 각각 `timeline_start`, `timeline_end`로 읽습니다.

## 상대경로와 결과 배치

Colab과 Mac 간편 CLI는 `path_mode: relative`를 사용합니다. 새 `--layout` 옵션은 결과를 `Generated/` 아래의 방향별 폴더에 둡니다.

~~~text
MyVideo/
├─ timeline.xlsx                    # 또는 timeline.csv
├─ Media/
│  └─ 카페 첫 부팅.mov
└─ Generated/
   ├─ preview/
   │  └─ index.html                 # --preview-only 결과
   ├─ vertical_9x16/
   │  ├─ MyVideo_vertical_9x16_clean.fcpxml
   │  ├─ MyVideo_vertical_9x16_with_titles.fcpxml
   │  └─ .build_media/              # 세로 사진 캐시
   └─ horizontal_16x9/
      ├─ MyVideo_horizontal_16x9_clean.fcpxml
      ├─ MyVideo_horizontal_16x9_with_titles.fcpxml
      └─ .build_media/              # 가로 사진 캐시
~~~

위 예시는 `--layout both` 결과입니다. 한 방향을 선택하면 해당 폴더만 생성됩니다. 기존 `--portrait`/`--landscape` 별칭과 `project.json` 고급 출력은 호환을 위해 설정된 `output_dir` 바로 아래의 평면 구조를 유지할 수 있습니다.

한글·공백·`#`는 XML media-rep URL을 만들 때 percent-encoding하고 XML 특수문자를 escaping합니다. XML만 다른 폴더로 옮기지 말고 `Media/`와 `Generated/`의 관계를 유지합니다.

고급 `project.json`의 `output_dir`도 기본적으로 프로젝트 내부로 제한합니다. 꼭 외부로 내보내야 할 때만 경로를 다시 확인하고 `--allow-external-output`을 명시합니다.
