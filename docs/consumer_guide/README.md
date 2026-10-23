# consumer_guide — 외부 프로젝트용 DB 사용 가이드 (원본)

다른 프로젝트(tj_asset 등)의 Claude 가 **DB 접속만으로** 계층3 사용법을 읽도록, 이 폴더가 원본이고
DB 의 `consumer_guide` 테이블과 `COMMENT ON` 이 배포본이다. 설계: `docs/plans/consumer_guide_in_db_2026-10-23.md`.

- `s01..s09_*.md` — 섹션 본문(영어, 머리말 `section/ord/title`). 소비자가 읽는 문서이므로 영어.
- `comments.sql` — 표/뷰/핵심 컬럼 `COMMENT ON` (멱등).
- 반영: `.venv/bin/python scripts/load_consumer_guide.py` (`--dry-run` 으로 미리보기). 스키마/규칙을 바꿀 때마다 같이 고치고 다시 적재한다.
- 소비자 쪽 진입점(소비자 CLAUDE.md 에 한 줄): `SELECT section, title, body FROM consumer_guide ORDER BY ord;`
- 이 폴더 외의 파일(docs/rules 등)은 소비자에게 공개하지 않는다. 가이드는 내부 규칙 번호(R###)를 쓰지 말고 현상으로 설명한다.
- 가이드 수정 시 확인: 예제 SQL 은 `tja_reader` 로 실행해 검증, 단위/누적 여부는 실측.
