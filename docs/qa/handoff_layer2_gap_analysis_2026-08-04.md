# 핸드오프 — 2015+ 계층2 적재 공백 원인 전수분해 + 아남전자(USD) 제외 (2026-08-04)

새 세션은 이 문서 → 필요하면 `docs/PARSING_RULES.md` 순으로 읽으면 된다.
**이번 세션은 재설계 본류(§5 브리지 swap) 진행 없음** — 계층2 적재 상태 감사 요청에서
시작한 별도 병행 트랙.

---

## 1. 이번 세션에 한 일 (2줄 요약)

1. **"2015+ 적재 중 남은 것" 질문에 답하려고 DB+원문 XML 직접 파싱으로 진짜 공백을 전수
   분해**했다 — 174건(2026-08-01판)이 사실 189건/6개 원인으로 확정됨.
2. 원인 중 하나(USD 표시)가 **아남전자 1개사뿐**임을 확인하고, 사용자 결정으로
   **소프트 제외**(`CORP_EXCLUDE_CORP_CODES`)를 구현·적용했다.

## 2. 최종 상태

| 구분 | 건수 |
|---|---:|
| 2015+ filings | 104,746 |
| report_lines 적재 | 102,067 (97.4%) |
| 미적재 | 2,679 |
| — 정정본(R2 정상, 2,268은 같은 기간 다른 보고서가 적재됨) | 2,285 |
| — **진짜 공백(원인 6종)** | **189건 / 176기간** |

USD(아남전자) 제외 적용 후 **실질 잔여 공백 = 159건**(189 − 30).

앱 유니버스 2,530 → **2,529사**(아남전자 `is_active=False`). DB·원문은 보존
(filings 127 · report_lines 6,217행 · note_lines 89,146행 — 2015~2018 원화 데이터).

## 3. 핵심 산출물

| 파일 | 역할 |
|---|---|
| `collector/config.py` | `CORP_EXCLUDE_CORP_CODES` 신설 — 이름/종목코드 규칙으로 못 거르는 개별 기업 제외 목록 |
| `collector/corp_collector.py` | `_is_excluded_corp()` + sync 후보 두 분기(krx_mode/DART단독) 모두 배선, `deactivate_excluded_corps()` 확장 |
| `scripts/redownload_missing_raw.py` | **신규.** 원문 파일 미실재 filing 재수집(NAS 마운트 전제, 기본 조회만, `--apply` 로 실행) |
| `tests/test_corp_exclude_codes.py` | 신규 6건 — 제외 술어 + **상장폐지 오판 안 됨**(`delisting.evaluate` 의 `listed` 소스 계약) 고정 |
| memory: `layer2-loading-status-2026-08-01.md` | 189건 원인표 + 내가 두 번 틀린 것 기록 |
| memory: `usd-corp-excluded-anam.md` | 제외 방식·안전성 근거 |

## 4. 189건 원인 (원문 파싱해서 확정, 전부 실측)

| 원인 | 건수 | 비고 |
|---|---:|---|
| 구형 레이아웃 미지원 | ~109 | 재무제표가 `XI. 재무제표 등` 아래. 대부분 2014년 제출(12월 결산 아닌 기업). 본문에 표가 **있는데** `_detect_body_statement_tables` 가 못 찾음 |
| 외화(USD) 표시 | 30 | **아남전자 단독** — 이번 세션에 제외 처리 완료 |
| XML 조용한 절단 | 19 | **웅진 9 + 웅진씽크빅 10**. 원문 488표 → 파싱 93표(비율 0.11~0.23 일정) |
| 원문 파일 없음 | 15 | 웰킵스하이텍3·유니켐3·한화에어로1 등 — NAS 마운트 후 `redownload_missing_raw.py` |
| 지금 돌리면 적재됨 | 10 | 스트라드비젼7·피스피스2·세미티에스1(download-only 공백기 다운로드만 된 신규상장사) |
| 단위 미선언 | 3 | 세화피앤씨·인카금융서비스·특수건설 각 1 |

별도로 **download-only 백로그 64건**(2026-07-14~08-03, 48개사, 2025 사업보고서 46건 포함)이
파싱 대기 중 — Phase 5 재개하면 자연 해소.

## 5. ★ 이번 세션에서 내가 두 번 틀린 것 (다음 사람 주의)

1. **"이엘피·윙스풋도 USD" 오판.** 처음엔 문서 *어딘가*의 USD 토큰을 정규식으로 잡았다.
   본문 재무제표 표 **주변**(같은 표 + 직전 형제 4개) 단위 선언만 보도록 좁히니
   **아남전자 1개사뿐**으로 확정됐다. → 단위 판정은 항상 표 스코프로 좁혀서 볼 것
   (`docs/PARSING_RULES.md` R1, 계층2 단위=열 원칙과 같은 함정).
2. **"적재분의 53%도 조용히 절단됨"은 계측 버그.** `b"<TABLE"` 바이트 카운트가
   `<TABLE-GROUP>` 태그까지 함께 세서 원문 표 수를 부풀렸다. 경계 앵커
   (`rb"<TABLE[\s>]"`)로 고치니 적재분 400건 무작위 표본이 **100% 완전 파싱**으로
   나왔다 — 절단은 웅진 계열에 국한, DB 전반 문제 아님. → 원문 대비 태그 카운트를
   셀 땐 항상 경계를 앵커할 것, 부분 문자열 매칭 금지.

## 6. 안전성 확인 사항 (다시 검증할 필요 없음)

- **`is_active=False` 를 손으로 찍는 건 무의미** — 상장 유지 중인 기업은 다음 sync 의
  upsert 가 `is_active=True` 로 되돌린다. 반드시 후보 필터(`_is_excluded_corp`)에 넣어야
  지속된다.
- **제외해도 상장폐지로 오판되지 않는다.** `delisting.evaluate` 의 `listed` 는
  `krx_client.listed_codes()`(거래소 상장 전 증권)이지 수집 유니버스가 아니다. 이 계약이
  깨지면 제외 기업 원문이 ⓪-4 로 아카이브 이관돼 버린다 — 회귀 테스트로 고정함
  (`tests/test_corp_exclude_codes.py::test_delisting_does_not_use_collection_universe`).

## 7. 남은 것 / 다음 후보

| 항목 | NAS 필요 | 상태 |
|---|---|---|
| **구형 레이아웃 감지기 확장**(109건, 효과 최대) | 개발 ❌ / 적재 ✅ | 미착수. `XI. 재무제표 등` 섹션 아래 재무제표를 `_detect_body_statement_tables` 가 찾도록 확장 필요 |
| 웅진 계열 XML 절단 원인 규명(19건) | 규명 ❌ / 적재 ✅ | 미착수. `recover=True` lxml 파서가 문서 중간에서 포기 — fatal parse error 위치 특정 필요 |
| 원문 15건 재다운로드 | ✅ | `scripts/redownload_missing_raw.py` 작성 완료, **NAS 마운트 대기** |
| 스트라드비젼 등 10건 재파싱 | ✅ | 대기 |
| 단위 미선언 3건 | 개별 확인 필요 | 미착수 |
| download-only 백로그 64건 | ✅ (+ Phase 5 재개 선행) | 대기 |

**세션 종료 시점에 NAS(`/Volumes/tj_finance_data`)가 마운트돼 있지 않았다** — 마운트해야
위 표의 "NAS 필요 ✅" 항목들과 오늘 18:00 데일리(`assert_storage` 가 막음)가 정상 진행된다.

## 8. 실행 명령

```bash
# NAS 마운트 확인 후 — 원문 유실 조회(조회만, 안전)
PYTHONPATH=. .venv/bin/python scripts/redownload_missing_raw.py

# 확인 후 실제 재수집
PYTHONPATH=. .venv/bin/python scripts/redownload_missing_raw.py --apply

# 회귀 테스트
.venv/bin/python -m pytest tests/test_corp_exclude_codes.py -q
```

## 9. Uncommitted 변경 (세션 종료 시점)

```
 M collector/config.py               (CORP_EXCLUDE_CORP_CODES)
 M collector/corp_collector.py       (_is_excluded_corp 배선)
?? scripts/redownload_missing_raw.py
?? tests/test_corp_exclude_codes.py
```

`docs/plans/rearchitecture_4layer.md` 의 M 은 **이번 세션 이전부터 있던 변경**(이번
세션에서 손대지 않음) — 별도 확인 필요.

커밋 여부는 사용자 판단 대기(요청 없었음).
