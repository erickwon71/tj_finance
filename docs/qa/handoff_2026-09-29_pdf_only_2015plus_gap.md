# 인계 — 2015+ PDF-only 정기보고서 결측 462건 + Track C 백필 시도 (2026-09-29)

> **★사용자 결정 (2026-10-01): 2015+ 캠페인 동안 PDF-only 462건은 "PDF-only 보류"로 둔다.**
> Track C 적재·백필은 하지 않는다. 이 필링에서 올라오는 검증 이슈(missing_row·unclassified 등)는
> fix 세션이 고치지 않고 `python scripts/hold_pdf_only_issues.py --apply` 로 **주차**한다
> (error_type 별 배치를 만들어 `waiting_decision`). 주차 배치에는 **절대 `batch reload` 를 하지 않는다.**
> 첫 실행: 배치 #66(missing_row 22건·9필링), #67(unclassified 2건·2필링).
> PDF-only 판정: 2015+ · 완료된 PDF 다운로드 있음 · 완료된 비-PDF 다운로드 없음 · report_lines 0행(462건 census 와 일치).
> 아래 "다음 fix 세션이 할 일"은 캠페인 종료 후 재개할 때의 목록이다.

## 배경

verify 러너가 19:13 "연속 3회 실패"로 정지(슬롯 `00131054:2015:Q3`, 유진증권). 원인 조사 중
발견: 이 슬롯의 정정본(`20151204000317`, [기재정정]분기보고서)이 DART에서 **PDF만** 제공되고
`report_lines`가 0행이라 검증 모델이 pass도 skip도 못 하고 막힘(DART 웹뷰 목차엔 재무제표
섹션이 실제로 있어 skip 사유가 성립하지 않음).

이 슬롯은 `ops.py`가 이미 자동으로 `blocked`로 격리해 러너 재개엔 지장 없음(claim이 blocked
슬롯을 재배정하지 않음) — 지금 당장 급한 문제는 아니지만, 근본원인을 추적하니 규모 있는
데이터 결손과 미완성 파서 배선이 드러났다.

## 근본원인 (기존 R103 기록의 미완 후속)

1. `docs/PARSING_RULES.md` R103(2026-09-13, `docs/qa/r103_...md` 아님 — R103 항목 참고) —
   예전 다운로더가 정기보고서를 PDF만 받고도 `download_tasks.status='completed'`로 마감해버려,
   표준파일(XML/XBRL)이 나중에 올라와도 데일리 재시도 대상에서 영영 빠지는 버그. 2026-09-13에
   **미래 다운로드에 한해** 수정됐고, "과거 이미 completed/pdf로 마감된 필링의 전사 census는
   미실시"로 다음 세션 숙제로 남아있었다. **오늘 그 census를 처음 실행함.**
2. 오늘 실측: `download_tasks.file_type='pdf' AND status='completed'`(2015+ annual/half/quarter)
   = **462건**, 그중 **461건이 `report_lines=0`**(사실상 전량 미적재).
3. DART `document.xml` API를 5건 표본으로 직접 재조회(오늘, 2026-09-29) → **전부 `[014]
   파일이 존재하지 않습니다`**. 즉 R103의 "기다리면 표준파일이 올라온다"는 재시도 전략은
   이 그룹엔 안 통한다 — XML/XBRL이 영영 안 올라오는 진짜 PDF-only 케이스로 보인다.
4. 프로젝트엔 이미 Track C PDF 파서(`fin2/extract/pdf.py`, "구형 2000년대 + 일부 분기/정정본"
   대응 명시)가 있지만 **데일리 파이프라인(`scripts/collect_new.py`)에 배선돼 있지 않고**,
   지금까지 실행된 건 전부 사람이 발견한 특정 배치(93건/195건/missing76건 등) 대상 1회성
   백필 스크립트뿐이다. 이 2015+ 462건 전체를 겨냥한 적은 없다.

## 검증 큐 현황(462건)

`verification.progress_filings.status` 기준: skipped 396(정상 — 모델이 DART 목차 직접
확인 후 정당하게 제외) · pending 62 · has_issues 3. 슬롯(progress) 기준 blocked는 **지금
1건뿐**(유진증권) — 나머지 61건은 러너가 아직 안 왔을 뿐, 도달하면 같은 패턴으로 막힐
가능성이 높다(아래 참고).

## pending 62건 상세조사 (오늘 실행, 커밋 안 됨 — 전부 스크래치패드 실행, DB 변경 없음)

**① 실제로 재무제표가 있는지**(PDF 전체 페이지, pdfplumber 텍스트 검색) — **62/62 전부**
BS/IS/CF 제목이 문서 어딘가에 존재. 즉 pending 62건은 거의 전부 유진증권과 같은 block
위험군이다(15페이지만 스캔한 1차 체크에선 23건만 잡혔었음 — 유진증권 실제 재무제표는
24페이지째부터, 총 235페이지. **짧은 페이지 캡으로 판단하면 과소추정된다**).

**② Track C(`fin2/extract/pdf.py::extract_pdf_facts`)로 실제 추출 시도**(DB 저장 안 함,
추출 결과만 확인) — 59/62 논제로 facts 산출, 3건(유안타증권 정정본 3건 전부, 같은 회사)
완전 0건.

**③ BS 항등식 자가검증**(자산총계 = 부채총계 + 자본총계, canonical 계정 중복 여부) —

| 분류 | 건수 | 비고 |
|---|---|---|
| clean(항등식 성립, 중복 없음) | 45 | 내부 정합성만 통과 — ★원문대조는 안 했음 |
| ambiguous(같은 canonical 계정에 서로 다른 값 중복) | 5 | 유진증권·삼영·흥국화재×2·대신증권 — **전부 증권/보험** |
| mismatch(중복 신호 없이 항등식 자체가 틀림) | 5 | 흥국화재(다른 필링)·우정바이오·상상인증권·시너지이노베이션·TS인베스트먼트 |
| nocanon(BS 총계가 canonical 매핑 자체가 안 됨) | 4 | 웹스 1 + 웹케시 3(같은 회사) |
| 완전 추출 실패 | 3 | 유안타증권 정정본 3건 전부 |

**결론(사용자 확인 후 보류 결정)**: ambiguous 5건은 대형 증권사/보험사 부속표(BIS비율·
순자본비율 등 감독 공시표)에 "자본총계"류 라벨이 재등장해 Track C가 같은 canonical
계정에 여러 후보값을 중복 적재하는 패턴 — 이대로 저장하면 계층3 max-abs 중복해소가
틀린(더 큰) 값을 채택할 위험(`key-bugs-fixed.md` 버그#8과 같은 계열). mismatch 5건은
중복 신호조차 없이 조용히 틀려서 셀프체크만으론 못 거른다. clean 45건도 내부 항등식만
확인했을 뿐 DART 원문 대조는 아직 안 됐다(★원본대조검증·짐작금지 원칙).

**→ 아무것도 저장하지 않기로 결정.** 462건 전체를 다음 fix 세션 항목으로 인계.

## 다음 fix 세션이 할 일

1. **Track C 앵커 경계 보강**: 증권/보험/캐피탈 업종의 감독 공시 부속표(BIS비율 등)를
   본문 BS/IS/CF 앵커와 구분하는 로직 추가(ambiguous 5건 — 다중 후보값 중 어느 게 진짜
   본문인지 판별). 유안타증권 3건(완전 실패)도 레이아웃 원인 규명 필요.
2. **mismatch 5건 개별 원인 규명** — 항등식이 조용히 틀리는 경로부터. 중복 신호가 없으므로
   셀프체크만으론 못 거른다 — 로직 버그 가능성 높음.
3. **462건 전체 census를 스코프로 확정**(오늘 462건은 annual/half/quarter만 봄 — report_type
   범위나 fiscal_period 정의를 넓혀 재확인 필요할 수도 있음).
4. 배선 완료 후 CLAUDE.md 필수 3단계 적용: ①`collect_new.py` 두 call site 배선 ②462건
   소급 백필 ③검증(회귀테스트 + 원문대조 표본 + Gate B 무영향).
5. R번호는 **이 문서 작성 시점엔 아직 안 붙임** — 실제 코드 수정 시 `docs/PARSING_RULES.md`에
   먼저 적고 붙일 것(동시 진행 중인 다른 fix 세션의 R194~R197과 번호 충돌 주의).

## 참고 — pending 62건 목록과 3단 분류는 재현 가능

이 문서의 숫자는 스크래치패드 1회성 스크립트로 재현했다(경로:
`/private/tmp/claude-501/.../scratchpad/pdf_scope_check_full.txt`,
`trackc_extract_try.txt`, `trackc_identity_check.txt` — 세션 종료 후 소멸하는 임시
디렉터리이므로 필요하면 아래 쿼리로 재생성):

```sql
SELECT dt.rcept_no, f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.report_nm, f.corp_cls
FROM download_tasks dt
JOIN verification.progress_filings pf ON pf.rcept_no = dt.rcept_no
JOIN filings f ON f.rcept_no = dt.rcept_no
WHERE dt.status='completed' AND dt.file_type='pdf'
  AND f.report_type IN ('annual','half','quarter') AND f.fiscal_year >= 2015
  AND pf.status='pending'
ORDER BY f.fiscal_year, dt.rcept_no;
```

관련: `docs/PARSING_RULES.md` R103 · `fin2/extract/pdf.py`(Track C) ·
`collector/downloader.py::_handle_standard_file_pending`.
