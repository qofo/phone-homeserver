# 참고 문서

[English](README.md) · <b>한국어</b>

이 네 편은 서버 자신의 작업 문서다. 폰에서 복사해 오면서 사설 주소를 예시 값으로 바꿨다.
**한국어만 있다.** 이중 언어 가이드의 일부가 아니라 내부 기록이고, 가이드가 다룰 수준보다
훨씬 자세하다.

| 문서 | 무엇인가 |
|:---|:---|
| [`SERVER_ENVIRONMENT_SPEC.md`](SERVER_ENVIRONMENT_SPEC.md) | 서버 환경 상세 명세서와 인수인계 가이드. 하드웨어, `proot` 계층, 모든 경로와 포트, 명령 치트시트 |
| [`CODE_SERVER_GUIDE.md`](CODE_SERVER_GUIDE.md) | 이 폰에서 code-server를 쓰는 방법. Remote-SSH가 왜 불가능한지 포함 |
| [`HUGO_MIGRATION_PLAN.md`](HUGO_MIGRATION_PLAN.md) | 블로그를 Hugo로 옮기는 계획서. 계획과 달라진 것을 이유와 함께 표로 정리 |
| [`STRESS_TEST_SPEC.md`](STRESS_TEST_SPEC.md) | 부하 시험 규격. 단계별 부하, 쿨다운, 그리고 이를 돌리는 클라이언트 도구 |

원본은 폰의 `/root`에 있고 그쪽이 source of truth다. 복사는 한 방향으로만 흐른다. 폰에서 이
저장소로이고, 그 과정에서 사설 주소를 바꾼다(`192.168.0.42`, `100.x.y.z`, `203.0.113.10`,
`<this-device>.<tailnet>.ts.net`). 여기 있는 사본을 고쳐 두고 폰이 따라오기를 기대하면 안
된다.

두 언어로 된 가이드 본문은 [`../`](..)와 [README](../../README.ko.md)의 표에 있다.
