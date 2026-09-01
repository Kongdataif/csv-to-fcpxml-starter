# GitHub 업로드 가이드

이 문서는 코드를 공개할 **배포자용**입니다. 순서는 `Mac에서 검증 → GitHub에 업로드 → 새로 내려받아 재검증 → Release 공개`입니다.

일반 사용자는 GitHub ID가 필요하지 않습니다. Public 저장소는 로그인하지 않아도 `Download ZIP` 또는 `git clone`으로 받을 수 있습니다. GitHub 계정과 ID는 코드를 올리는 배포자에게만 필요합니다.

## 전체 순서

1. Mac 로컬 테스트
2. 실제 저장소 주소 설정
3. 공개하면 안 되는 파일 확인
4. GitHub Public 저장소 생성
5. 코드 push
6. 새 폴더에 clone 후 다시 실행
7. Final Cut 가져오기 확인
8. `v0.6.0` Release 생성
9. 선택 기능인 공개 Colab 확인

## 1. GitHub에 올리기 전에 Mac 테스트

저장소 폴더의 VS Code Terminal에서 실행합니다.

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
bash scripts/run_beginner_demo.sh
```

확인할 것:

- 전체 자동 테스트 통과
- `vertical_9x16`과 `horizontal_16x9` 결과가 각각 생성됨
- 각 FCPXML의 해상도와 FPS 자동 검증 통과
- `--preview-only` HTML에서 세로·가로 크롭·여백·자막 안전영역 확인
- 세로·가로 Title XML을 Final Cut에서 가져올 수 있음
- 기본 Share 영상에 Basic Title이 보임

실제 Mac 확인 전에는 Release를 만들지 않습니다.

## 2. GitHub에서 빈 Public 저장소 만들기

1. GitHub에 로그인합니다.
2. 오른쪽 위 `+ > New repository`를 선택합니다.
3. 저장소 이름을 정합니다. 예: `csv-to-fcpxml-starter`
4. 사용자가 자유롭게 내려받을 수 있게 `Public`을 선택합니다.
5. 로컬에 이미 파일이 있으므로 `Add a README`, `.gitignore`, License는 추가하지 않습니다.
6. `Create repository`를 누릅니다.

생성 후 표시되는 HTTPS 주소를 복사합니다.

```text
https://github.com/내-GitHub-ID/csv-to-fcpxml-starter.git
```

## 3. 선택 기능인 Colab 주소 설정

Mac 로컬 실행만 배포한다면 이 단계는 건너뛸 수 있습니다. 공개 Colab도 제공하려면 배포자의 GitHub ID와 저장소 이름으로 README 버튼과 노트북 주소를 맞춥니다.

```bash
python scripts/configure_github.py 내-GitHub-ID \
  --repo csv-to-fcpxml-starter \
  --ref v0.6.0
```

여기서 GitHub ID는 URL을 만드는 **저장소 소유자 이름**입니다. 최종 사용자가 입력하는 값이 아닙니다.

`v0.6.0` 태그는 아직 만들지 않았으므로 Colab 링크가 바로 열리지 않을 수 있습니다. Release 태그를 만든 뒤 확인합니다.

## 4. 실제 사용자 파일 제외

다음 명령으로 올릴 파일을 확인합니다.

```bash
git status --short
find . -type f -size +10M -not -path './.git/*' -print
```

올리면 안 되는 것:

- 실제 촬영 원본과 개인 사진·영상·음악
- 사용자 기획표와 자막 전문
- `projects/`, `Generated/`, `.build_media/`, 결과 ZIP
- `.venv/`
- 계정 화면, 비밀키, 토큰, 개인 절대경로
- 라이선스가 불명확한 폰트와 미디어

예제는 직접 만든 짧은 합성 미디어 또는 파일 자리를 설명하는 README만 사용합니다.

## 5. Terminal에서 GitHub에 올리기

현재 폴더가 아직 Git 저장소가 아닐 때만 처음 한 번 실행합니다.

```bash
git init
git branch -M main
```

변경 내용을 확인하고 commit합니다.

```bash
git add .
git status --short
git commit -m "feat: add Mac-first CSV to FCPXML workflow"
```

앞에서 복사한 저장소 주소를 연결하고 올립니다.

```bash
git remote add origin https://github.com/내-GitHub-ID/csv-to-fcpxml-starter.git
git push -u origin main
```

이미 `origin`이 있다면 새로 추가하지 말고 확인합니다.

```bash
git remote -v
```

인증이 필요하면 GitHub Desktop, GitHub CLI 또는 브라우저 인증을 사용합니다. 비밀번호나 Personal Access Token을 명령문·README·스크린샷에 적지 않습니다.

## 6. GitHub Desktop으로 올리는 방법

Terminal의 Git 명령이 낯설다면 [GitHub Desktop](https://desktop.github.com/)을 사용할 수 있습니다.

1. GitHub Desktop에 로그인합니다.
2. `File > Add Local Repository`로 이 프로젝트 폴더를 선택합니다.
3. 저장소가 아니라는 안내가 나오면 로컬 저장소 생성을 선택합니다.
4. 왼쪽 변경 파일에서 실제 미디어나 결과물이 없는지 확인합니다.
5. Summary에 변경 내용을 적고 `Commit to main`을 누릅니다.
6. `Publish repository` 또는 `Push origin`을 누릅니다.
7. 공개 배포라면 `Keep this code private`가 선택되지 않았는지 확인합니다.

웹 브라우저의 파일 드래그 업로드보다 Git 또는 GitHub Desktop을 권장합니다. 숨김 폴더인 `.github`와 `.gitignore`까지 빠짐없이 올리기 쉽기 때문입니다.

## 7. GitHub에서 확인

저장소 첫 화면에서 다음이 보여야 합니다.

- `README.md`
- `START_HERE.md`
- `make_xml.py`
- `templates/`
- `notebooks/`
- `.github/workflows/test.yml`

`Actions` 탭의 테스트가 통과하는지도 확인합니다.

## 8. 새 폴더에 다시 clone

현재 개발 폴더가 우연히 동작하는 문제를 잡기 위해 새 위치에 다시 받습니다.

```bash
cd ..
git clone https://github.com/내-GitHub-ID/csv-to-fcpxml-starter.git release-check
cd release-check
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
bash scripts/run_beginner_demo.sh
```

소유한 짧은 테스트 미디어가 있는 `projects/release-test`를 별도로 준비했다면 미리보기도 확인합니다.

```bash
python make_xml.py projects/release-test --layout both --preview-only
```

Mac에서 두 FCPXML을 Final Cut으로 가져옵니다. 새 clone에서 성공해야 배포 파일만으로 재현된 것입니다.

## 9. 오류 수정과 재검사

오류가 있으면 개발 폴더에서 수정한 뒤 다음 순서를 반복합니다.

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
bash scripts/run_beginner_demo.sh
git add .
git commit -m "fix: describe the verified correction"
git push
```

Final Cut 검사가 필요한 변경은 실제 import와 Share까지 다시 확인합니다.

## 10. Release 만들기

1. GitHub 저장소의 `Actions`가 통과했는지 확인합니다.
2. `Releases > Draft a new release`를 누릅니다.
3. `Choose a tag`에서 `v0.6.0`을 만듭니다.
4. 방금 Mac과 Final Cut에서 검증한 commit을 선택합니다.
5. 제목과 변경 내용을 적습니다.
6. `Publish release`를 누릅니다.

이미 공개한 태그를 다른 commit에 다시 붙이지 않습니다. 수정판은 `v0.6.1`처럼 새 태그를 사용합니다.

Release 설명에는 다음만 간단히 적으면 됩니다.

- Mac 로컬 실행이 기본 권장 경로임
- `.xlsx`/UTF-8 `.csv`와 사진·영상 지원
- `portrait`, `landscape`, `both` 지원
- Basic Title FCPXML, clean FCPXML, SRT 생성
- 실제 확인한 macOS·Final Cut Pro 버전
- 알려진 제한

## 11. 공개 사용자 관점 최종 확인

로그아웃 또는 시크릿 창에서 다음을 확인합니다.

1. Public 저장소가 열림
2. `Code > Download ZIP` 가능
3. README의 상대 링크가 열림
4. ZIP을 푼 뒤 [Mac 가이드](MAC.md)만 보고 실행 가능
5. GitHub ID 입력 없이 clone 가능
6. Colab을 제공한다면 버튼이 `v0.6.0` 태그의 노트북을 엶

더 엄격한 보안·태그 검사는 [릴리스 관리자 체크리스트](PUBLISHING.md)를 사용하세요.
