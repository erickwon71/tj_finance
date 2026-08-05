# 핸드오프 — ⓪-4 file_path 재발 방지 + 08-04 원인표 재확인 (2026-08-05 저녁)

새 세션은 이 문서 → 필요하면 `docs/PARSING_RULES.md` 순으로 읽으면 된다.
`handoff_layer2_silent_loss_2026-08-05.md`(오늘 낮 작성)의 **바로 다음 이어지는 세션**이다.
그 문서가 남긴 "다음 후보" 중 **⓪-4 file_path 배선**을 처리하고, 08-04 핸드오프의 189건
원인표가 지금 상태와 맞는지 실측으로 재확인했다.

---

## 1. 이번 세션에 한 일 (3줄 요약)

1. `fix/layer2-legacy-layout-and-appropriation` 브랜치를 main 에 ff-only 병합 + 미커밋
   잔여 3건 커밋 + push 완료(별도 대화 턴에서, 이 문서는 그 이후 진행분 포함).
2. **⓪-4 재발 버그를 고쳤다** — 상장폐지 원문 이관 시 `download_tasks.file_path` 가
   갱신 안 되던 결함. 과거 이미 발생한 12개사 952건도 소급 교정했다.
3. 08-04 핸드오프의 "189건 원인표"를 활성기업 기준으로 다시 돌려 **지금 상태와 정확히
   맞아떨어지는지 재확인**했다. 대부분 해소됐고, 재확인 과정에서 **새 패턴 하나**
   ("XML 파싱 자체 실패" 9건)를 발견했다.

## 2. 최종 상태

```
report_lines   37,404,896      note_lines      245,249,511
report_tables  12,787,259      archived corps  12 (원문 보존)
active corps   2,530
```

- git main = `df13bfe`, origin 과 완전 동기화(push 완료), working tree 깨끗.
- pytest: `fin2/tests tests` 405 passed / 1 failed(`test_lxintl_facility_table_dropped`,
  사전부터 있던 별건, biz_section 소관 — 이번 세션과 무관).
- 브랜치 `fix/layer2-legacy-layout-and-appropriation` 는 병합 후 삭제됨.

## 3. ⓪-4 file_path 재발 방지 (오늘의 핵심 수정)

### 원인
`collector/delisting_archive.py::archive_confirmed()` 가 상장폐지 확정 기업의 원문
폴더를 `shutil.move()` 로 NAS 아카이브에 통째로 옮기면서 `corporations.archive_path`
만 갱신하고 **`download_tasks.file_path` 는 옛 경로(raw_report 쪽, 이제 없음) 그대로
뒀다.** 그러면 `load_report_lines.py`·`note_lines_sync.py`·`cf_da_sync.py` 등 file_path
로 원문을 여는 모든 로더가 "file missing" → `status='skip'` 으로 **오류 없이 영구
스킵**한다. 2026-08 상장폐지 12사 923건이 이렇게 났었고, 당시엔 file_path 를 못 고쳐
파생 데이터를 통째로 삭제하는 것으로 우회했다(`scripts/purge_delisted_data.py`).

### 수정 (커밋 `df13bfe`)
- `_repoint_download_tasks()` 신설 — 이동 직후 **같은 트랜잭션**에서
  `corporations.archive_path` 갱신과 함께 그 corp 의 filing 전부를 새 경로로 재배선.
- `archive_confirmed()`/`run_daily()` 반환값에 `repointed` 건수 추가, 로그에 노출.
- 회귀 테스트 3건 추가(`tests/test_delisting_archive.py`, 총 15건 통과):
  재배선 확인 · 드라이런 무변경 · 타 기업 미간섭.
- 데일리 배선은 **추가 배선 불필요** — `scripts/collect_new.py::_sync_delisting_archive()`
  가 이미 `run_daily()` 하나만 부르므로 이 함수를 고치면 자동 반영된다(call site 1개,
  `--standardize-only` 는 원래부터 의도적으로 미배선 — 문서화돼 있음).

### 소급 백필 (사용자 승인 후 적용 완료)
`scripts/repoint_archived_file_paths.py`(신규) — 이 결함이 살아있던 동안 이미 아카이브된
12개사의 stale file_path **952건**을 DB 텍스트만 교정(파일 이동 없음). dry-run 검증
(불일치 0건) 후 `--apply` 실행, 재배선 후 전건 실파일 존재 확인 완료.

**부수 발견**: macOS APFS 는 `Path.iterdir()` 로 읽은 한글 폴더명을 **NFD(분해형)** 로
반환하는데 `download_tasks.file_path` 는 다운로드 시점에 만든 **NFC(조합형)** 문자열이다.
화면엔 똑같이 보이지만 바이트가 달라 단순 `str.find()` 비교가 통째로 실패했다
(현대홈쇼핑 등 927건이 처음엔 "폴더명 미포함"으로 오판됨) — `unicodedata.normalize("NFC", ...)`
로 흡수. **이 함정은 한글 폴더명이 걸린 문자열 비교 어디서든 재발할 수 있다.**

## 4. 08-04 원인표 재확인 결과 (실측)

`handoff_layer2_gap_analysis_2026-08-04.md` 의 189건 6원인표가 지금도 유효한지
`scripts/probe_residual_gap_breakdown.py` 의 쿼리에 `corporations.is_active = true`
필터를 더해 **활성기업 한정으로 재실행**했다(원본 쿼리는 상장폐지 12사의 이번 세션
purge 로 되살아난 952건까지 잡아버려 628건으로 나옴 — 이건 결함이 아니라 §6.1 의도한
결과, 활성기업 필터로 걸러야 진짜 잔여공백이 나온다).

**결과: 정확히 24건** — `handoff_layer2_silent_loss_2026-08-05.md` §2 표의 "24" 와
정합. 08-04 의 6원인 중 어디가 살아있고 어디가 사라졌는지:

| 08-04 원인 | 건수 | 재확인 결과 |
|---|---:|---|
| 구형 레이아웃 미지원 | 109 | **완전 해소** — 24건 중 "구형서식" 태그 0건 |
| 외화(USD) 표시 | 30 | **완전 해소** — 아남전자 FX 지원으로 정상 적재, 유니버스 복귀 |
| XML 조용한 절단(웅진) | 19 | **완전 해소** — 24건 중 웅진/웅진씽크빅 0건 |
| 원문 파일 없음 | 15 | **부분 해소** — 웰킵스하이텍·한화에어로스페이스는 이제 파일이 있음(재다운로드됨). 유니켐 등은 24건에서 완전히 사라짐. 다만 아래 §5 참고: 파일은 생겼는데 **파싱 자체가 실패**하는 새 문제로 옮겨감 |
| 지금 돌리면 적재됨 | 10 | **대부분 해소** — 이엘피·윙스풋·인카금융서비스·특수건설 등이 "표잡힘(현대)-적재만안됨" 5건으로 남아 재로드만 하면 됨 |
| 단위 미선언 | 3 | **사실상 해소** — 인카금융서비스·특수건설이 위 5건에 포함(F1 단위=열 수정으로 이제 정상 인식). 세화피앤씨는 24건에 없음(해소) |

**결론: 08-04 가 지목한 6원인 중 유효하게 남은 건 없다.** 24건은 전부 이번 세션
이전(08-05 낮)의 수정으로 이미 발생한 **잔차**이고, 아래 §5 가 그 정체다.

## 5. 잔여 공백 24건의 정확한 구성 (신규 실측, ★다음 세션이 볼 것)

| 건수 | 원인 태그 | 성격 |
|---:|---|---|
| **9** | **XML 파싱 자체 실패**(`_parse_xml_file` → None) | ★**새로 드러난 패턴** — 원문은 있는데 lxml 이 fatal error 로 완전히 포기. 웅진의 "부분 절단"과 다르다(그건 표는 줄어도 파싱은 됨). 대상: 박셀바이오·웰킵스하이텍(3건)·자비스·특수건설·팬엔터테인먼트·포시에스·한화에어로스페이스 |
| 6 | 표못잡음 — 본문섹션은 있는데 표 분류 실패 | 현대 서식 섹션(`SEC_CONSOL_FS`/`SEC_SEP_FS`) 은 잡히는데 그 안에서 표를 못 찾음. 구형 레이아웃 문제와 다른 결함 |
| 5 | 표잡힘(현대) — 적재만 안 됨 | **파싱은 정상, 로더만 안 돌았다.** `load_report_lines.py --rcept-file` 로 바로 채울 수 있음(이엘피·윙스풋·인카금융서비스·특수건설 등) |
| 4 | 표못잡음 — 본문·구형 섹션 둘 다 없음 | 다른 서식(양지사·웰킵스하이텍·이노시뮬레이션·티로보틱스) |

전체 rcept_no 목록은 세션 로그에 있고, 아래 §7 명령으로 즉시 재현 가능.

## 6. 다음 후보 (우선순위 순)

1. **표잡힘(현대)-적재만안됨 5건 재로드** — 가장 쉬움, 파싱 결함 없음. rcept_no 5개를
   `--rcept-file` 로 넘기면 끝(§7).
2. **XML 파싱 자체 실패 9건 원인 규명** — 이번에 처음 분해된 패턴. 웅진 절단 수정
   (`2bf225a`)과는 다른 결함일 가능성이 높다. `_parse_xml_file` 이 어느 지점에서
   포기하는지 fatal error 위치부터 특정해야 한다(웅진 때 썼던
   `scripts/probe_legacy_layout_gap.py` 류 도구를 참고해 새로 만들 것).
3. **표못잡음(현대섹션있음) 6건** — 구형 레이아웃과 다른 결함이니 형태 열거하지 말고
   구조로 봐야 한다(`[[layer2-silent-loss-patterns]]` 교훈 그대로 적용).
4. ③ 표제 인식 수정(0b93816)의 소급 미반영분 ~260건 — 전량 `--recheck` (~14h) 필요,
   여전히 미착수.
5. `stash@{0}`(아남전자 소프트제외 코드) — FX 지원으로 완전히 대체됨, **버려도 된다**.
6. 08-04 병행 트랙의 나머지(download-only 백로그 64건+) — Phase 5 재개 선행 조건 그대로.

## 7. 실행 명령

```bash
# §5 "표잡힘(현대)-적재만안됨" 5건 재로드 — rcept_no 실측값(이 세션 §5 결과)
cat > /tmp/gap_ready.txt <<'RCEPT'
20210517000207
20160513002038
20160330001530
20170516000038
20151116001903
RCEPT
PYTHONPATH=. .venv/bin/python scripts/load_report_lines.py --rcept-file /tmp/gap_ready.txt

# 활성기업 한정 잔여공백 재현 — probe_residual_gap_breakdown.py 원본은 필터가 없어
# 상장폐지분(§9 참고)까지 잡으므로, 재현하려면 SQL 의 grp CTE 에
# `JOIN corporations c ON c.corp_code = f.corp_code ... AND c.is_active = true` 를
# 더해서 돌릴 것(아직 원본 파일에 정식 반영 안 함 — §6 후보 3).

# 회귀
.venv/bin/python -m pytest fin2/tests tests -q
```

## 8. 이번에 만든/바꾼 파일

| 파일 | 내용 |
|---|---|
| `collector/delisting_archive.py` | `_repoint_download_tasks()` 신설 + 배선 |
| `tests/test_delisting_archive.py` | 재배선 회귀 테스트 3건 추가(총 15건) |
| `scripts/repoint_archived_file_paths.py` | 신규. 과거 아카이브분 소급 재배선(1회 실행 완료) |

커밋: `df13bfe fix(delisting): ⓪-4 원문 이관 시 download_tasks.file_path 미갱신 재발 방지`

## 9. ★ 다음 사람이 알아야 할 것

- **`probe_residual_gap_breakdown.py` 는 활성기업 필터가 없다.** 상장폐지 기업의
  파생데이터를 의도적으로 지운 뒤(§6.1, 08-05 낮) 이 스크립트를 그대로 돌리면 628건이
  나와서 마치 크게 퇴보한 것처럼 보인다 — **결함이 아니라 필터 누락**이었다. 다음에
  이 스크립트를 쓸 사람은 `corporations.is_active = true` 조인을 잊지 말 것(이번
  세션에서 임시로 stdin 스크립트로 우회했고, 아직 원본 파일에 정식 반영 안 함 — §6-4
  후보).
- **"XML 파싱 자체 실패"와 "XML 조용한 절단"은 다른 결함이다.** 전자는
  `_parse_xml_file`이 `None`을 반환(완전 포기), 후자는 파싱은 되는데 표 일부만 누락.
  둘을 섞어서 "웅진 수정으로 다 해결됐다"고 단정하면 안 된다 — 이번 재확인으로 후자만
  해소됐고 전자는 별도 미해결로 새로 드러났다.
