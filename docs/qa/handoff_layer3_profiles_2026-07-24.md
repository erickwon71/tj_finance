# 핸드오프 — 계층3 정제 완료 + 업종 revenue 프로파일 + IS 추출갭 복구 (새 세션 시작점, 2026-07-24)

> **이 문서부터 읽을 것.** 이전 핸드오프 = `docs/qa/handoff_layer3_skeleton_2026-07-23.md`(보존) ·
> L3-4 분류/판정 = `docs/qa/layer3_L3-4_diff_classification_2026-07-23.md` ·
> 업종 revenue 설계 = `docs/plans/insurer_revenue_composition_2026-07-24.md` · 메모리 = [[rebuild-phase-a3-done]]

---

## 0. 한 줄 요약
**신 체인 계층3 정제 사실상 완료 + 업종별 revenue 프로파일(보험·은행·증권) + IS 추출갭 복구.**
inspect 전량 v3 정답(결함 0). ★V2는 정답 아님 — **DART 원문 기준** 검증. **다음 = P2 계층4(업종별
tearsheet+스크리너) → L3-5 swap.** ⚠ 사용자가 `--recheck`(요약서식 전코퍼스 확대) 실행 중 → **완료 후
`build_std_v3.py --all` 재빌드 필수**.

## 1. ⚠⚠ 지금 진행 중인 것 (새 세션 첫 확인)
- **사용자가 `--recheck` 실행 중**(본인 터미널, `caffeinate -i nohup python scripts/load_report_lines.py
  --recheck > recheck.log 2>&1 &`, ~9.5h). 요약재무정보 추출수정을 **전 코퍼스(102,633 filing)** 에 소급.
- **완료 후 반드시**: `python scripts/build_std_v3.py --all`(25분) — 재추출분 + 이번 세션 **전 프로파일**을
  std_v3 에 통합 반영. (프로파일은 코드에 커밋됐으나 std_v3 미반영 상태일 수 있음.)
- 완료 확인: `recheck.log` 마지막 `[load-lines] 완료 X.XXh`. 그 후 재빌드 → L3-4 재측정으로 효과 확인.

## 2. 이번 세션에 한 일 (커밋순, 전부 main)
### 계층3 revenue 정제
- **금융업 매출 정제**(`0b37f9a`): 근본원인=충돌보류. combine `_reduce_conflict` 강화(EPS우선→min-depth
  총계우선→0헤더제외) + is.revenue 승급. v2only 2,401→1,667.
- **업종 revenue 프로파일**(`f895643`·`5ef0b07`·`7ca2ce5`·`0a80586`·`8fc9e08`·`c93f67f`): `fin2/layer3/
  industry_profiles.py` `RevenueProfile` 레지스트리 + std_v3 `industry_lines` JSONB 성분보존. 사용자 결정=
  **합산(GROSS)**.
  - **보험**(65): 보험(영업/서비스)수익+투자(영업/서비스)수익. operating_income=원문 영업이익(이미 정답).
  - **증권/지주 총계보유**: `_reduce_conflict` grand-total 라벨 우선(수수료수익 성분 이김).
  - **은행**(64121 순수은행 + 64992 은행지주, signature=순이자손익 게이트): 이자+수수료+보험+기타 gross.
    신한34.7·KB45.5·하나27.8·우리23.2조. 일반지주(롯데 등)는 signature 로 배제.
  - **순액증권**(66121, signature=순수수료손익): 수수료+이자+트레이딩+기타. 삼성증권12.4조.
  - **★증권성 금융지주(한국금융지주 00432102)=revenue NULL**(NO_REVENUE_CORPS): 매출액 개념 없음(사용자:
    "NaN=사실"). op_income 이하는 정확. BNK(은행지주)와 IS 마커 동일→자동구분 불가라 curated 세트.
- **루닛형 부호정규화**(`a2afc78`): 순'손실' 단독라벨+양수 → −value(combine `_loss_signed`, P&L 5종).
  루닛 net_income −73.6B(원문 일치). build_std_v3 --all 재빌드 반영됨.
- **inspect 미일치 드릴**(`05f6c0f`): `scripts/layer3_inspect_drill.py`. 미일치 124=basis_fallback 114 +
  손실반전 10, **unexplained 0 = 순수 v3 결함 없음**. faithfulness basis버그 교정 86%→**100%(908/908)**.

### 계층2 IS 추출갭 복구 (B-case, 14→1)
- 진단: BS있고 IS없는 corp-year 14건. **★인코딩 교훈**: 구 KOSDAQ XML 은 헤더 utf-8 선언이나 실제 EUC-KR.
- **B1(4)**(`fef4e40`): stale데이터 → `scripts/reload_report_lines_corp.py` 재적재(삼성화재2020/21+SCE 등).
- **B2 요약서식(9)**(`4dc9831`·`52b0ab7`·`de34f78`·`46d7dae`): 구형 요약재무정보가 [제목][기간][회사명·단위]
  별도 <P>/표 분리 → 추출기 미스. 수정 4종(전부 declared_unit용 title_text 불변·fallback 가산적):
  ①`title_text_for_classify`(메타줄 최대3칸 스킵) ②`declared_unit` (3)메타형제 단위스캔(재무제표명 경계정지=
  엘브이엠씨 회귀차단) ③`declared_unit` 직전형제 전체텍스트(200자절단 우회) ④내용기반 BS오분류교정(BS로
  분류됐으나 매출+영업이익 있고 자산총계 없는 표→IS, 지노믹트리 주석오분류만·컴투스 과도발동 회피).
  **엠로·에스앤디×3·바이오플러스·애드바이오텍·시큐센·젠큐릭스·지노믹트리 복구, 값 전부 DART 원문 일치.**
- **잔여1=슈프리마 2015**(손익·현금흐름 전항목 0 = 물적분할 stub, 정당한 부재. 사용자 원문확인).
- 부수효과: 케이뱅크·우리금융지주 등 요약/under-추출 filing 도 복구 → **--recheck 로 전 코퍼스 확대**(진행중).

## 3. 신 체인 상태 (std_v3)
- 185,214행·2,534사. industry_lines: 보험12사+은행/지주/증권. **재빌드 대기**(--recheck 완료 후).
- gross MATCH 98.4%대. inspect 전량 v3 정답. IS추출갭 14→1(슈프리마 stub만).

## 4. 다음 세션 — 무엇을 할지 (순서)
1. **★--recheck 완료 확인 → `build_std_v3.py --all` 재빌드**(§1). L4-4 재측정으로 요약서식 확대 효과 확인.
2. **P2 계층4**: 업종별 tearsheet(`industry_lines` profile/성분 소비 — 보험/은행/증권 네이티브 항목) +
   스크리너 정규화 revenue 배선. PRD `docs/prd/05_visualization.md`·`06_screener.md`. 한국금융지주형(revenue
   NULL)은 op_income 로 표시.
3. **★L3-5 swap**(최종): 앱 재배선 std_v2→std_v3(app/data 소비처) · 구 체인 제거(fact_v2·std_v2·text.py
   텍스트트랙) · report_lines 데일리 배선(collect_new.py **두 call site**) · 야간 잡 재설치(deploy/launchd) ·
   최근 IPO 6사 sync 재개(filings=0 자동해결).

## 5. 상태 주의 (★반드시)
- ⚠ **V2는 정답 아님**(사용자 지침) — 검증은 **DART 원문** 기준. v2 는 참고만.
- ⚠ **야간 잡 전량 삭제 유지** — swap 전까지 구 체인 오염 방지([[nightly-jobs-paused-phase-a3]]).
- ⚠ **앱은 여전히 구 체인**(std_v2) 사용 — swap 안 함(L3-5).
- ⚠ raw_report 심링크 = SD카드(`/Volumes/dart_data`). NAS 원복 별도.
- ⚠ report_lines 대용량(62.9M) — label_raw/node_role 전량 정규식 스캔 느림(인덱스 없음). LIKE+LIMIT 나
  std_v3 조인으로 바운드.
- ⚠ 은행지주 엣지: **한국금융지주만** revenue NULL(curated). 다른 증권지주 추가 시 `NO_REVENUE_CORPS` 등록.
- venv=`.venv`. 신규 스크립트: layer3_diff_classify·inspect_drill·insurer_revenue_survey·
  combine_regression_probe·fin_revenue_survey·reload_report_lines_corp.
