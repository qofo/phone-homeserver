# 이미지

[English](README.md) · <b>한국어</b>

여기에는 두 종류의 자산이 있다.

**생성된 다이어그램과 터미널 기록** — `.svg` 파일 전부이고,
[`make_assets.py`](make_assets.py)가 만든다. 배경을 자기가 들고 있어서 GitHub의 밝은
테마와 어두운 테마에서 모두 읽히고, 텍스트라서 diff에 무엇이 바뀌었는지 드러난다. SVG를
직접 고치지 말고 스크립트를 고친다.

```bash
python3 docs/images/make_assets.py
```

| 파일 | 쓰이는 곳 |
|:---|:---|
| `architecture.svg` | README — 계층 구조와 세 개의 신뢰 구역 |
| `boot-chain.svg` | README, `04-always-on` — 트리거, 런처, 감독자 |
| `network-paths.svg` | README, `05-private-access` — 공개 경로와 tailnet 전용 경로 |
| `publish-pipeline.svg` | `02-web-server` — 원본 하나, 서버 둘 |
| `health-check.svg` | `04-always-on` — `pgrep` 대신 프로브 |
| `term-install.svg` | README, `01-install` — Termux에서 우분투 셸까지 |
| `term-status.svg` | README — 세 가지 `status` 명령 |
| `term-specs.svg` | README — 하드웨어가 실제로 내주는 자원 |
| `term-verify.svg` | `06-operations` — 폰 밖에서 동작을 증명하기 |

**사진과 스크린샷** — 이것은 만들어 낼 수 없다. 아래는 문서에 자리를 비워 둔 목록이다.
각 줄에 쓸 파일명이 적혀 있으니, 파일을 이 디렉터리에 넣고 한 줄을 붙이면 끝난다.

## 이미 들어온 것

| 파일 | 담긴 내용 | 쓰이는 곳 |
|:---|:---|:---|
| `shot-blog-home.png` | 고정 공개 주소로 열린 블로그 | README, "무엇이 돌아가는가" |
| `shot-dashboard.png` | 실시간 대시보드. 코어별 사용률, 메모리, 스왑, 배터리, 온도 | `06-operations` 6.3절 |
| `shot-battery-alert.jpg` | 80% 충전기 분리 알림. Termux 웨이크 락, Tailscale 연결과 나란히 | `06-operations` 6.1절 |
| `shot-jobs.jpg` | 등록된 작업 네 개가 모두 보이는 `termux-job-scheduler -p` 출력 | `04-always-on` 4.3절 |
| `shot-ngrok-warning.png` | ngrok의 경고 페이지 | `03-public-address` 3.3절 |
| `shot-tailscale-app.png` | 폰이 연결된 Tailscale 앱 — *마스킹함* | `05-private-access` 5.2절 |
| `shot-docs-viewer.png` | 문서 뷰어의 목록 화면 — *마스킹함* | `05-private-access` 5.4절 |

## 아직 필요한 사진

신경 써서 찍을 가치가 있는 것은 첫 번째 하나다. 전제가 사실임을 보여 주는 유일한 이미지다.
이 저장소의 나머지는 빌린 VPS에서 돌려도 똑같아 보인다. 그리고 GitHub은 저장소가 공유될 때
README의 첫 이미지를 링크 미리보기로 쓴다.

| 파일명 | 담을 내용 | 들어갈 곳 |
|:---|:---|:---|
| `photo-phone-server.jpg` | 일하고 있는 폰. 충전기를 꽂고, 세워 두고, 화면에는 대시보드나 Termux 세션. 가로로, 정면에서 | README, 제목 아래 |
| `photo-case-off.jpg` | *선택* — 뒷판을 벗긴 폰. 발열 대책 그 자체다 | `06-operations` 6.2절 |

## 아직 필요한 스크린샷

| 파일명 | 담을 내용 | 들어갈 곳 |
|:---|:---|:---|
| `shot-termux-ubuntu.png` | `proot-distro login ubuntu` 직후의 Termux. `cat /etc/os-release` 출력이 화면에 있어야 한다. 빈 프롬프트는 아무것도 보여 주지 못한다 | `01-install` 1.4절 |
| `shot-code-server.png` | 파일을 실제로 열고 터미널 패널에 출력이 있는 code-server. 로딩 중 화면이 아니라 | `05-private-access` 5.7절 |
| `shot-android-battery-opt.png` | Termux의 배터리 최적화가 **해제**된 안드로이드 설정 화면 | `01-install` 1.1절 |

## 스크린샷을 커밋하기 전에

이 저장소는 공개되어 있고, 스크린샷은 코드 블록보다 많은 것을 흘린다. 이미지마다 다음을
확인한다.

- **tailnet 이름과 MagicDNS 이름** — `something.tailnet-name.ts.net`. 문서와 같은 방식으로
  `<this-device>.<tailnet>.ts.net`으로 가린다.
- **집 공인 IP, LAN 서브넷, DuckDNS나 공유기 호스트네임.** 문서는 `203.0.113.10`,
  `192.168.0.42`, `100.x.y.z`를 대역 값으로 쓴다.
- **code-server 비밀번호**, 그리고 인증서 개인 키.
- 뷰어 목록의 **비공개 문서 제목**과, 열린 문서 안에서 읽히는 내용.
- **안드로이드 상태 바** — 통신사 이름, 알림, 와이파이 SSID.
- 브라우저 프로필에 뜨는 **구글·깃허브 계정 이름**.

가능하면 흐리게 하는 대신 잘라 낸다. 약하게 준 블러는 복원될 수 있고, 모자이크 처리한
글자도 마찬가지다. 되돌릴 수 없는 마스킹은 불투명한 막대뿐이다.

여기 있는 이미지 중 셋을 그렇게 가린 뒤 커밋했다. ngrok 페이지에는 폰의 공인 IPv6 주소가,
Tailscale 화면에는 계정 주소와 실명과 기기 세 대의 주소가, 뷰어 목록에는 공개하지 않은
개인 프로젝트의 제목과 실제 tailnet 주소가 찍혀 있었다.

## 추가하는 방법

표의 이름으로 파일을 여기에 저장한 뒤, "들어갈 곳"에 적힌 자리에 아래 줄을 붙인다. 옆의
`.ko.md` 문서에도 한국어 설명으로 같은 줄을 넣는다.

```markdown
![충전기를 꽂고 서비스 중인 폰](docs/images/photo-phone-server.jpg)   <!-- README.md에서 -->
![충전기를 꽂고 서비스 중인 폰](images/photo-phone-server.jpg)        <!-- docs/ 문서에서 -->
```

사진은 400KB, 스크린샷은 250KB 아래로 유지한다. 이 저장소는 사이트를 서비스하는 그 폰에도
복제된다. 긴 변을 1600px로 줄이면 보통 충분하다.

```bash
# ImageMagick이 있는 기계에서
magick photo.jpg -resize 1600x -quality 82 photo-phone-server.jpg
```
