# trade_payables additive override (5개사) — 원문대조+수정설계 (2026-08-14)

**상태: 구현 완료 (단, §3의 curated dict 키를 corp 단독 → (corp, fiscal_year,
fiscal_period) 3-튜플로 교정). 최종본은 `docs/PARSING_RULES.md` R17.**

구현 중 실측으로 두 가지 함정을 발견해 이 문서의 §3 설계를 그대로 적용할 수
없었다:
1. 형제 라벨이 AccountMapper에서 **다른 canonical로 매핑**돼(`bs.other_current_payables`
   등) `_resolve()`가 자기 canonical의 `rows`만 보면 override가 한 건도 발동
   안 함(최초 구현이 이 상태였고, 유닛테스트 목은 이 함정을 못 걸러 통과했음).
2. corp 단독 키로 발동시키자 목표기간(대부분 FY2025~2026Q1)은 고쳐졌지만
   **같은 회사의 과거 모든 기간(2010~2024, LG화학만 100건+)이 새로 fail_b로
   회귀** — "두 라인 합=report_won"은 원문대조로 확인한 그 특정 필링에서만
   성립하고 회사 단위 성격이 아니었다. scoped 백필+Gate B recheck로 발견,
   즉시 DB 원상복구 후 사용자에게 보고→"회사+기간 범위로 재설계" 승인 받아
   (corp, fy, period) 3-튜플 키로 교정, 재검증 완료(fail_a 671→662, fail_b
   회귀 0). 상세는 R17 참고.

[[gate-b-faila-residual-triage-2026-08-14]] §1 후속. 5개사 전부 raw XBRL 직접대조로
근본원인을 확정했다(짐작 없음). (아래 §1~§4는 원설계 그대로 보존 — §3의 구현
코드만 R17에서 period-scoped로 교정됐다.)

## 1. 원문대조 결과 — "두 줄 합산"이 아니라 진짜 XBRL 개념이 근거

애초 가설은 "BS 본문의 매입채무 + 형제라인(F) 두 개를 더하면 report_won과 일치"였다.
그런데 원문을 직접 열어보니, 실제로는 **그 합계와 정확히 같은 값을 가진 별도의 단일
XBRL fact가 필링 안에 이미 존재**한다 — 다만 그 fact가 report_lines의 표/텍스트
추출 경로로는 잡히지 않는 위치(주석 세부 공시표 안)에 있을 뿐이다. 두 가지 다른
concept로 갈린다(회사마다 다름, 짐작 아니라 grep 직접 확인):

| corp | 회사명 | 근거 concept | 원문 값 | report_won |
|---|---|---|---:|---:|
| 00356361 | LG화학 | `ifrs-full_TradeAndOtherPayablesUndiscountedCashFlows`[MaturityAxis=NotLaterThanOneYear], ADECIMAL=-6 | 10,518,983(×10⁶) | 10,518,983,000,000 ✓ |
| 01093007 | LS에코에너지 | 〃, ADECIMAL=-3 | 91,835,434(×10³) | 91,835,434,000 ✓ |
| 00109310 | 대동기어 | 〃, ADECIMAL=0 | 51,813,089,762 | 51,813,089,762 ✓ |
| 00113544 | 대한화섬 | `ifrs-full_TradeAndOtherCurrentPayables`(top-level, sub-axis 없음), ADECIMAL=0 | 54,617,564,136 | 54,617,564,136 ✓ |
| 00138446 | 아가방컴퍼니 | 〃 | 32,396,373,183 | 32,396,373,183 ✓ |

**대조군(01412822 솔루스첨단소재, triage §2의 최초 사례)**: 위 두 concept 모두 원문에
**존재하지 않음**(grep 0건) — 이 회사만 다른 메커니즘(note_lines 만기분석표 텍스트
전사에서만 유도 가능, XBRL fact 자체가 없음)이라 이번 5개사와 분리해서 다룬 것이
맞았다.

**회계항등식 관점의 함의**: "매입채무(F) + 형제 유동채무라인(F) = report_won"이
5/5 정확히 성립하는 건 우연이 아니다 — 만기분석표 "1년 이내" 버킷이나
`TradeAndOtherCurrentPayables`는 정의상 "매입채무+기타 유동 채무의 합"이므로, BS
본문에 그 구성요소들이 전부 라인으로 나와 있다면 더한 값이 같아야 정상이다. 즉
이 5개사에 한해서는 **"두 줄 합산" 구현이 안전하고 근거가 확실**하다(진짜 XBRL
fact와 독립적으로 검증됨).

## 2. 왜 블랭킷 규칙이 아니라 여전히 curated인가

R16(§2)에서 이미 실측한 것처럼, "F 라인 두 개를 항상 더한다"는 블랭킷 규칙은
위험하다 — 대다수 회사는 매입채무 단독 F 라인이 이미 정답이고, 부채>유동부채
섹션엔 매입채무 외에도 무관한 F 라인(미지급비용·예수금·선수금 등)이 다수 존재해
임의의 두 라인을 더하면 우연히 다른 숫자와 일치하거나 완전히 틀린 값을 낼 위험이
크다. 게다가 "더할 두 번째 라인의 라벨"이 회사마다 전부 다르다(기타지급채무/
기타채무/단기미지급금/기타유동금융부채) — 구조적으로 일반화할 신호가 없다. R16과
동일하게 **5개사 curated dict**로 좁힌다.

## 3. 수정 설계

`fin2/layer3/combine.py`에 신규 curated dict:

```python
# ★trade_payables additive override(2026-08-14): 원문 XBRL 직접대조로 확인(둘 다
# report_lines 텍스트추출로는 안 잡히는 위치에 있는 진짜 fact와 정확히 일치 —
# ifrs-full_TradeAndOtherPayablesUndiscountedCashFlows[MaturityAxis=1년이내] 또는
# ifrs-full_TradeAndOtherCurrentPayables). BS 본문엔 매입채무+형제 유동채무 라인이
# 둘 다 이미 존재하지만 결합 총계(P) 라인 자체가 없는 레이아웃 — 그 두 라인의 합이
# report_won. 라벨이 회사마다 전부 달라 일반화 규칙 금지(R16 §2와 같은 위험).
# docs/plans/gate_b_faila_trade_payables_additive_design_2026-08-14.md
_TRADE_PAYABLES_ADDITIVE_OVERRIDE_CORPS = {
    "00356361": ("매입채무", "기타지급채무"),        # LG화학
    "00113544": ("매입채무", "기타채무"),             # 대한화섬
    "00109310": ("유동매입채무", "단기미지급금"),     # 대동기어
    "00138446": ("유동매입채무", "기타유동금융부채"), # 아가방컴퍼니
    "01093007": ("매입채무", "기타채무"),             # LS에코에너지
}
```

`_resolve()`의 `bs.trade_payables` 처리 블록(R16 override 바로 다음, stage-rank
이전)에 추가:

```python
if c == "bs.trade_payables" and corp in _TRADE_PAYABLES_ADDITIVE_OVERRIDE_CORPS:
    want = _TRADE_PAYABLES_ADDITIVE_OVERRIDE_CORPS[corp]
    picked = {}
    for r in rows:
        if _is_noncurrent(r):
            continue
        label = _norm_label(r.get("label_raw"))  # 괄호 주석번호 등 제거된 정규화 라벨
        for w in want:
            if w not in picked and label.startswith(w):
                picked[w] = r["value"]
    if len(picked) == len(want) and all(v is not None for v in picked.values()):
        confirmed[c] = sum(picked.values())
        continue
```

- `_is_noncurrent()` 재사용(R15) — 비유동 변형(장기매입채무 등)이 잘못 집계되지 않게.
- `startswith` 매칭(정확히 `==` 대신) — 라벨에 "(주4,5,19,36)" 같은 각주 번호 접미사가
  붙는 경우가 흔함(LG화학 "기타지급채무 (주3,5,30)" 등, 원문 확인됨).
  `_norm_label()`이 공백은 이미 제거하므로 접미사만 남는다.
- 두 라벨 다 못 찾으면(필링마다 라벨이 미세하게 바뀔 수 있음) 원래 stage-rank 경로로
  자연스럽게 폴백 — 결측을 새로 만들지 않음.

## 4. 검증 계획(구현 시 필수, R16과 동일 절차)

1. **회귀 0 확인**: `report_lines` 전수 시뮬레이션 재사용 — 5개사만 값이 바뀌고 다른
   회사는 0건 변화(curated dict라 원리상 자명하지만 오타/스코프 실수 방지 차원 재확인).
2. **pytest**: `test_combine_curated_overrides.py`에 이 5개사용 유닛테스트 추가(등재
   회사는 합산 발동, 라벨 하나만 못 찾으면 폴백, 대조군 비등재 회사는 무영향).
3. **소급 백필**: 5개사만 scoped(`build_std_v3.py --corp 00356361,00113544,00109310,
   00138446,01093007 --year-min 1999`).
4. **Gate B 재검증**: 5개사만 scoped(`gateb_audit.py --corp-file <5개사> --recheck`) —
   trade_payables fail_a 감소분이 이번 세션 확인한 8~9건(LG화학4·대한화섬1·대동기어1·
   아가방컴퍼니2·LS에코에너지1)과 일치해야 함.
5. **`docs/PARSING_RULES.md`**: R16 옆에 이어지는 항목(R17 또는 R16 본문에 추가)으로
   등재.

## 5. 장기 대안(이번 설계 범위 밖, 참고용)

원문대조로 밝혀진 진짜 근거가 `ifrs-full_TradeAndOtherCurrentPayables`/만기분석표
concept라는 점은, 이 5개사에 국한되지 않는 **더 일반적인 해법의 여지**를 시사한다 —
R14/R10처럼 이 두 concept를 Track A(XBRL 원문) 방식으로 직접 읽어 report_lines에
없는 "결합 유동채무" 후보로 공급하는 계층2 신규 모듈. 이러면 01412822류(만기표에
비슷한 값이 있지만 이 concept 자체가 없어 이번 5개사와는 다름, §1 대조군 참고)도
케이스에 따라 회수될 수 있고, 향후 같은 레이아웃의 신규 회사도 자동 커버된다.
**단, `TradeAndOtherCurrentPayables`가 항상 "결합 총계"를 의미하진 않는다** — 오전
triage(01090471 씨아이에스)에서 이미 확인했듯, 이 concept가 "매입채무 외의(non-trade)
유동채무"라는 정반대 의미로 쓰인 회사도 있다(같은 taxonomy concept의 다의성, R14류
교훈과 동일). 그래서 일반화하려면 XBRL 인라인 값 하나만으로 판단하지 말고 라벨/문맥
교차검증이 필요 — 이번 curated override보다 훨씬 큰 별도 트랙. 이번엔 범위에서
제외, 5개사 curated override로 좁혀 먼저 처리하는 것을 권장.

## 근거
- 원문 XBRL 직접 grep: LG화학 `20260313001195.xml`(18253행), 대한화섬
  `20260318001465.xml`(12851행), 대동기어 `20260317000606.xml`, 아가방컴퍼니
  `20260320001348.xml`(15044행), LS에코에너지 `20260316001365.xml`. 대조군
  01412822 `20250319000924.xml`(두 concept 모두 grep 0건).
- `docs/qa/gate_b_faila_residual_triage_2026-08-14.md` §1(최초 발견) ·
  `docs/PARSING_RULES.md` R16(같은 계열의 curated-override 철학 선례) ·
  `scripts/probe_faila_residual_2026-08-14.py`(분류 스크립트).
