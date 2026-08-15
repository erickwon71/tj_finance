# 설계 — Gate B `face_audit.py` 리더 결함 수정 (controlling_ni 신규 30건, 2026-08-15 작성)

> **★§2-B(②구조적 후보누락, 24행) 구현+검증+DB반영 완료(2026-08-15, 같은 날 후속
> 세션, 사용자 승인 하에 진행)** — `docs/PARSING_RULES.md` R25 등재, 상세는 그쪽 참고.
> §2-A(①FX표시통화, 두산밥캣 1개사)는 규모확인만 끝났고 **여전히 미구현**(옵션 B 권장,
> 구현은 별도 승인 필요).

> 배경 조사 전체 = 메모리 `gateb-controlling-ni-new30-rootcause-2026-08-15`(원문 XML
> 대조 로그 포함, 이 세션에서 8개사 30행 전수 확인).

---

## 0. 요약

- **대상**: Gate B `controlling_ni` fail_a 중 이전 세션(R24)이 손대지 않은 30행(8개사).
  전수 원문대조 결과 **std_v3(db_won)이 전부 정답, Gate B(`fin2/audit/face_audit.py`)의
  독립 재추출값(report_won)이 전부 오답** — std_v3 데이터는 손대지 않는다.
- **메커니즘은 2종류, 서로 성격이 다르다**:
  - **①FX 표시통화** — 두산밥캣(01032486) 1개사·6행. 연결재무제표 표시통화가 **USD**인데
    Gate B가 원화로 오인. **영향범위가 controlling_ni 한 필드가 아니라 그 6행의 전 필드
    (22개 전부)** — 별도 메커니즘, 별도 설계 필요(§2-A).
  - **②구조적 후보누락** — 나머지 7개사·24행(코아시아씨엠·이노메트리·진영·모비데이즈·
    유니온·코렌텍·판타지오). 원문 자체가 라벨/ACODE 를 헷갈리게 배치했는데(회사고유
    확장 ACODE 사용, 총포괄손익 절에 표준 ACODE 오태깅, SCE 합계열 오인, EPS 라인
    오태깅) Gate B 의 후보 스캔이 **정답 후보 자체를 놓친다** — controlling_ni 필드에만
    국한. `fin2/layer3/combine.py`가 R24(2026-08-15)에서 std_v3 쪽에 이미 적용한 "구조기반
    후보보강" 아이디어를, 원문 XML을 직접 읽는 Gate B 쪽에 독립적으로(모듈 재사용 아님,
    같은 발상을 재구현) 적용한다(§2-B).
- **핵심 설계 원칙(둘 다 공통)**: **후보를 고르지 않고 넓히기만 한다.** `audit_fields()`의
  PASS 판정은 이미 "db_won 이 후보 집합 어디엔가 있으면 PASS"(단일 최선값 선택 아님,
  `face_audit.py:838`) — 그러므로 정답 후보를 후보 풀에 추가로 끼워넣기만 하면, 기존
  로직이 스스로 PASS 로 승격시킨다. 새 오답을 낼 수 있는 새 "선택" 코드를 만들지 않는다
  (단조 개선 — 기존 PASS 를 절대 못 깨뜨림).

---

## 1. 근본원인 상세

### 1-A. ①FX 표시통화 — 두산밥캣, 6/6행 원문대조 완료

원문 노트: *"지배기업의 기능통화는 대한민국 원화이며, 연결재무제표는 달러(USD)로
표시되어있습니다."* — 즉 지배기업(별도) 재무제표는 원화, **연결**재무제표만 달러로
작성한다. XBRL `ACODE` 태깅은 달러 원값 그대로다(예: `ifrs-full_
ProfitLossAttributableToOwnersOfParent` = 413,029천USD). Gate B 는 ADECIMAL 로 단위만
환산하고 통화는 검사하지 않으므로 이 값을 그대로 원화로 취급 → `report_won`.

std_v3(db_won)은 DART 가 USD 표시 필터社에 첨부를 요구하는 **비XBRL 참고표** "나. 원화기준
재무정보"(서울외국환중개 평균/기말 매매기준율로 환산, DART 필수 첨부 섹션)의 값을 정확히
읽어와 저장한다 — 6/6행 전부 백만원 단위까지 정확히 일치 확인(재현 스크립트는 메모리 참고).

★★**영향범위 정정(이번 설계 작업 중 발견)**: DB 재조회 결과 이 6행은 controlling_ni
하나만 fail_a 가 아니라 **행 전체(총자산·매출액·현금흐름 등 22개 필드 전부)가 fail_a**
다 — 표시통화가 다르면 그 통계표 전체가 다 스케일이 어긋나기 때문. 즉 이 메커니즘은
controlling_ni 문제가 아니라 **"두산밥캣 연결 6개 기간 자체가 Gate B 감사 불가"** 문제다.

### 1-B. ②구조적 후보누락 — 7개사·24행, 대표사례 원문대조 완료(전사 미실행 항목은 표기)

| 회사 | 행수 | 세부 패턴 |
|---|---:|---|
| 코아시아씨엠(01031502) | 6 | 회사고유 확장 ACODE(`entity01031502_...`)가 "당기순이익의 귀속" 절의 정답 행에 붙어있고, 표준 ACODE는 "당기**총포괄**이익의 귀속" 절에 오태깅됨 |
| 이노메트리(01258710) | 5 | 상동(회사고유 ACODE=순이익귀속 정답, 표준 ACODE=총포괄손익귀속 오태깅) |
| 진영(00816933) | 1 | 상동 |
| 모비데이즈(01493535) | 7 | 상동(대표사례 2025Q1 원문대조 완료) |
| 유니온(00144252) | 1 | 상동 + report_won 이 **주당순이익(EPS, 357원)**행에 표준 ACODE 가 오태깅된 극단 사례 |
| 코렌텍(00541437) | 2 | 표준 ACODE 자체가 IS 본문엔 없고 **SCE(자본변동표)** 안에서만 태깅됨. SCE 의 "축 없음" 열은 지배주주+비지배주주 **합계**(산술 검증: db_won+NCI열=report_won 정확 일치)인데 Gate B 가 이를 "무차원=home=정답"으로 오인. 진짜 정답은 IS 본문의 회사고유 확장 ACODE 행 |
| 판타지오(00231691) | 2 | 가장 지저분한 사례 — 같은 결합표(손익+포괄손익) 안에 "당기순이익의 귀속" 절이 **두 번**(1차=회사고유 ACODE=정답, 2차=표준 ACODE=오답 — 그 직후 "포괄손익의 귀속" 절이 4개 기간 전부 0으로 비어있어 필터社의 중복입력 오류로 추정). db_won 은 SCE 열·EPS 각주표와도 교차일치(3중 확인) |

공통 구조: 모두 IS(손익계산서, 총포괄손익계산서 결합표 포함) 본문에 **"...의 귀속"** 이라는
소제목 행이 있고, 그 아래 "지배기업(소유주)"/"비지배(지분/주주)" 두 회원 행이 따라온다.
Gate B 의 `read_report_face_xbrl()`(face_audit.py:265)는:

1. `_XBRL_PREFIXES = ("ifrs-full_", "dart_")` 만 인정 → 회사고유 확장 ACODE(`entity{corp}_
   ...`)는 애초에 후보 풀에 안 들어간다(295~298줄).
2. 후보를 **acode 단위**로만 모으고(concept_map 매핑 필요) 그 acode 가 문서 어느
   섹션/표에서 왔는지는 전혀 안 본다 — "총포괄손익의 귀속" 절과 SCE 표 안의 값도
   `is.controlling_ni` 후보로 똑같이 들어간다(라벨/섹션 무관, ACODE 매핑만 봄).

`fin2/layer3/combine.py::_ni_attribution_structural_candidates()`(R24, 2026-08-15)가
std_v3 쪽에서 이미 겪고 고친 것과 **정확히 같은 근본원인**이다(그쪽은 `report_lines.
section_path`를 쓰고, 여긴 원문 XML 을 직접 읽으니 재구현이 필요할 뿐).

---

## 2. 제안 설계

### 2-A. ①FX 표시통화 — 규모 확인 완료(2026-08-15 추가 세션), **옵션 B로 재권장(정정)**

**전수 스캔 완료**: `raw_report`(NAS `/Volumes/tj_finance_data` + SD카드 미러
`/Volumes/dart_data`, 양쪽 독립 스캔 결과 완전 일치 — 교차검증됨)에서 "원화기준
재무정보\|원화환산 재무정보\|원화 표시 재무정보" 문자열을 가진 필링을 `*.xml`
전수 grep. **문자열 매치 자체는 5개사**였으나, **후속 원문대조·DB대조 결과 4개사는
프로젝트 유니버스 밖(외국기업 제외 정책 대상)으로 확인 — Gate B 영향 0건.**
아래 판단은 그 대조 결과를 반영해 정정한 것(원래 이 표 아래 있던 "옵션 A 권장"
문단은 유니버스 확인 전 판단이라 폐기).

| corp_code | 회사명 | 유니버스 소속 | 근거 |
|---|---|---|---|
| 00799070 | 딥커머스(구 이스트아시아홀딩스인베스트먼트리미티드) | **아님** | `corporations`·`face_audit` 0행. 홍콩 설립·중국 자회사 지배 지주회사(원문 확인) — [[foreign-corps-excluded]] 정책의 전형 프로필 |
| 00800084 | 씨엑스아이 | **아님** | `corporations`·`face_audit` 0행. 원문 STKCD `900120`(9로 시작) 직접 확인, 자회사 CKH Food & Health 기능통화 RMB |
| 01032486 | 두산밥캣 | **맞음** | KOSPI 241560, `face_audit`에 정상 존재(§1-A 원인규명 완료) |
| 01041828 | JTC | **아님** | `corporations`·`face_audit` 0행. 원문 종목코드 `950170`(9로 시작, DR/원주) 직접 확인, 별도·연결 재무제표 모두 표시통화=일본 엔화 |
| 01442115 | 소마젠 | **아님** | `corporations`·`face_audit` 0행. [[foreign-corps-excluded]] 메모리에 2026-07-19 삭제 대상 21개사 중 하나로 이미 명시적으로 이름이 올라있던 회사 |

**즉 실제 Gate B 대상(유니버스 안)은 두산밥캣 1개사뿐이다.** 나머지 4개사는
`corporations`·`face_audit` 양쪽 다 0행 — Gate B가 아예 감사하지 않는 대상이라 fail_a에
전혀 안 걸린다. (부수 발견: 이 4개사의 raw_report 폴더는 NAS·dart_data 양쪽에 여전히
남아있음 — 2026-07-19 외국기업 purge 스크립트가 이들 폴더까지 지웠는지는 불확실하고,
확인·정리는 이번 작업 범위 밖. 필요하면 별도 트랙으로.)

**권장 판단(정정)**: §2-A 원 설계의 기준("1~3개사면 B, 5개사 이상이면 A")을 **유니버스
안 기업 수(1개사)** 기준으로 다시 적용하면 → **옵션 B(저비용 pending 강등) 권장으로
되돌아간다.** 두산밥캣 1개사·6행을 위해 새 Track D 리더를 만드는 건(옵션 A) 투자
대비 회수가 작다.

| 옵션 | 내용 | 비용 | 획득 |
|---|---|---|---|
| **B. 저비용 회피(권장, 정정)** | "원화기준 재무정보" 섹션 존재 + XBRL 값과 db_won 배율이 900~1600 사이(전형적 USD/KRW 환율대) 인 필링을 감지하면, 그 행 전체를 `fail_a`가 아니라 새 pending 사유(`FX_PRESENTATION_CURRENCY`)로 강등 | 낮음(감지 로직만) | fail_a 오탐만 제거, 실질 검증은 없음(std_v3 값을 믿고 넘어가는 것) |
| A. Track D 신설(비권장, 정정) | "원화기준 재무정보" 섹션을 감지하면, 그 안의 BS/IS/CF 참고표를 Track B(`read_report_face_text`)와 같은 방식(라벨+숫자 셀, `account_mapper.map()`)으로 파싱해 FaceLine 생성 → Track A 결과에 **병합**(USD 표시 감지 시 이 Track D 결과로 **교체**, 원 Track A 의 USD 원값은 버림) | 중간(새 리더 1개, 표 파싱은 기존 `_read_table` 패턴 재사용 가능) | 22개 필드 전부 진짜 검증(pass) — 1개사·6행 분량엔 과투자 |

**최종 권장**: 두산밥캣 1개사면 옵션 B로 충분. **단, 이 권장도 이 문서에서 확정하지
않는다 — 구현 착수는 사용자 승인 필요.**

### 2-B. ②구조적 후보누락 — `read_report_face_xbrl()`에 구조기반 후보보강 추가(권장, 즉시 착수 가능)

`combine.py`의 R24 와 같은 원칙: **새 "선택" 로직을 만들지 않는다.** 기존
`read_report_face_xbrl()`이 만든 `FaceLine` 리스트에, 아래 규칙으로 찾은 추가 후보를
**끼워넣기만** 한다(`is.controlling_ni`·`is.noncontrolling_ni` 두 canonical 한정).

**규칙** (raw XML, TR 시퀀스를 문서 순서로 순회하며 상태기계로 판정):

1. TR 의 라벨 텍스트(그 행의 ACODE 없는 첫 TE, 기존 `_cell_text` 재사용)에 "귀속"이
   포함되고 "순이익"|"손익"이 포함되되 "포괄"이 **없으면** → 이후 TR들을 "순이익귀속
   섹션"으로 진입.
2. 그 섹션 안에서 라벨에 "비지배"가 있으면 `is.noncontrolling_ni` 후보 행, 없고 "지배"가
   있으면 `is.controlling_ni` 후보 행(정확히 각 1개씩만 — 모호하면 스킵, 짐작 금지 —
   `_ni_attribution_structural_candidates()`의 "정확히 1개씩" 원칙 그대로 이식).
3. 그 행의 TE[@ACODE] 값 셀은 **ACODE prefix 필터를 이 두 canonical 한정으로 완화**해
   회사고유 확장(`entity\d+_...`)도 인정 — 다른 모든 canonical 은 기존 `_XBRL_PREFIXES`
   필터 그대로 유지(범위 최소화, 부작용 없음).
4. 섹션은 다음 "귀속"/"포괄" 매치 TR 을 만나거나 2개 회원(지배+비지배)을 다 채우면 종료.

**SCE(자본변동표) 배제가 따로 필요 없는 이유**: SCE 는 지배/비지배 구분을 **열 헤더**로
표현하지("지배기업 소유주지분"이 컬럼명), "...의 귀속"이라는 **행 라벨**을 쓰지 않는다
(코렌텍 실측 확인). 그래서 위 상태기계는 SCE 표 안에서는 애초에 발동하지 않는다 —
별도의 "SCE 표 배제" 로직(테이블 제목 분류 등)을 추가할 필요가 없다(불필요한 복잡도 회피).

**"우선순위" 결정이 필요 없는 이유**: `audit_fields()`(752줄)의 PASS 판정은 `val in
won_vals`(838줄) — 후보 집합 중 db_won 과 일치하는 게 하나라도 있으면 그걸로 끝난다.
판타지오처럼 정답/오답 두 후보가 공존해도(§1-B), db_won 과 일치하는 쪽이 자동으로
매치되어 PASS — **어느 게 "더 맞는지" 가릴 필요가 전혀 없다.** 오답 후보가 같이
들어있어도 기존 PASS 를 깨뜨리지 않는다(그 오답이 다른 행의 db_won 과 우연히 일치할
가능성은 이미 §2-B 규칙의 좁은 범위—"...귀속" 섹션 내부, 지배/비지배 정확히 1개씩—로
낮음. 완전배제는 아니나 R24 가 같은 원칙으로 32/51건에 오탐 0건이었던 선례 있음).

---

## 3. 구현 스케치 (미착수, 승인 후 진행)

```python
# fin2/audit/face_audit.py 신설 함수 (초안, 미검증)

_NI_SECTION_LABEL_RE = re.compile(r"귀속")

def _ni_attribution_structural_candidates(root) -> list[FaceLine]:
    """combine.py::_ni_attribution_structural_candidates() 의 발상을 raw XML 에
    독립 재구현(모듈 재사용 아님 — face_audit 의 독립성 원칙 유지).
    is.controlling_ni / is.noncontrolling_ni 후보만 보강, 다른 canonical 은 불변."""
    extra: list[FaceLine] = []
    in_section = False
    for tr in root.findall(".//TR"):
        tes = tr.findall("TE")
        if not tes:
            continue
        label = _cell_text(tes[0])  # 라벨은 관례상 첫 TE(값 TE 는 ACODE 있음)
        has_acode_cells = any(te.get("ACODE") for te in tes[1:])
        if not has_acode_cells:
            # 소제목 행(섹션 헤더) 판정
            if _NI_SECTION_LABEL_RE.search(label) and ("순이익" in label or "손익" in label) \
                    and "포괄" not in label:
                in_section = True
            else:
                in_section = False
            continue
        if not in_section:
            continue
        canon = None
        if "비지배" in label:
            canon = "is.noncontrolling_ni"
        elif "지배" in label:
            canon = "is.controlling_ni"
        else:
            in_section = False  # 섹션 형태 예상 밖 — 더 안 봄(짐작 금지)
            continue
        for te in tes[1:]:
            acode = te.get("ACODE", "")
            if not acode or len(acode) > 255:
                continue
            # ★ 여기서만 entity{corp}_ 확장 prefix 도 인정(다른 canonical 은 기존 필터 유지)
            ctx = parse_acontext(te.get("ACONTEXT", ""))
            if not ctx.parsed or ctx.is_dimensional or ctx.col_index != 0:
                continue
            displayed = parse_displayed(_cell_text(te))
            if displayed is None:
                continue
            adecimal = _parse_adecimal(te)
            extra.append(FaceLine(
                statement="IS", basis=ctx.basis, acode=acode, canonical=canon,
                label=label[:80], displayed_value=displayed, adecimal=adecimal,
                is_cumulative=ctx.is_cumulative,
            ))
        in_section = False  # 회원 행 1개 소비 후 다음 회원까지는 계속 열어둘지 —
                             # 실제 구현 시 "지배+비지배 둘 다 나올 때까지 유지" 로 조정 필요
    return extra
```

`read_report_face_xbrl()` 끝에서 `lines.extend(_ni_attribution_structural_candidates(root))`
한 줄 추가(기존 dedup 로직과 자연히 병존 — canonical 다르면 같은 key 라도 안 겹침).

위 스케치는 상태기계 세부(섹션을 언제 닫는지 등)가 아직 거칠다 — **실제 구현 시 R24 의
`_ni_attribution_structural_candidates()`(combine.py:1870)를 참고해 "정확히 1개씩"
가드를 그대로 이식**(양쪽 다 있어야 채택, 하나만 있으면 스킵)하는 편이 더 안전하다.

---

## 4. 이번 설계 범위 밖

- **①FX 표시통화 나머지 4개사**: 원문대조·DB대조 완료(2026-08-15) — 딥커머스·씨엑스아이·
  JTC·소마젠 전부 프로젝트 유니버스 밖(외국기업 제외 정책 대상, `corporations`·
  `face_audit` 0행)으로 확인됨. Gate B 영향 0건, 조사 완료. raw_report 원문 폴더도
  정리 완료(2026-08-15, 같은 날 후속 지시) — NAS는 `archive/foreign_excluded/2026/`
  으로 이관(207개 파일, 이관 전후 개수 일치 확인), SD카드(dart_data)는 삭제(개수
  일치 확인 후). `corporations` 테이블에 이 4개사 행 자체가 없어 DB 갱신은 불필요.
- **그룹B/C 잔존 4건**(오브젠·KBI메탈 2025H1·한화생명 2건) — 별도 원문대조 필요,
  이번 30건과 무관(핸드오프 메모리 `gateb-controlling-ni-next-session-handoff-2026-08-15`).
- **그룹A mismap 잔여 19건(Phase 2)** — `gateb-controlling-ni-mismap-design-2026-08-15`
  §4, std_v3(combine.py) 쪽 잔여 작업, 이번 설계와 무관.
- Gate B 구조기반 후보보강을 controlling_ni 외 다른 필드(trade_payables 등 라벨 모호성
  있는 필드)로 일반화하는 것 — 이번엔 controlling_ni 전용으로 좁게 설계(R24 도 같은
  선택을 했다, 범위 최소화).

---

## 5. 검증 계획 (구현 승인 시)

1. §2-B(구조기반 후보보강) 구현 후 이번에 확인한 24행(②) 전부 fail_a → pass 전환 확인.
2. `pytest tests/ fin2/tests/` 전체 그린 확인(회귀 0).
3. 이 24행 밖의 controlling_ni pass 행들이 그대로 pass 인지 재확인(단조성 — 후보
   추가만으로 기존 PASS 를 깨뜨리지 않는다는 설계 전제 실측 검증).
4. §2-A(FX 표시통화, 이제 대상은 두산밥캣 1개사로 확정)는 옵션 확정 후 별도 검증계획
   (B 선택 시 pending 전환 + gate_status 재계산 확인, A 선택 시 22개 필드 전부 pass
   전환 확인).

---

## 6. 산출물

- 이 문서.
- 원문대조 근거는 이번 세션 스크래치패드(`/private/tmp/.../verify_doosan_bobcat.py`,
  세션 임시파일 — 재현하려면 재작성 필요) + 메모리
  `gateb-controlling-ni-new30-rootcause-2026-08-15`.
- §2-A 규모 확인용 전수 스캔(`grep -rl "원화기준 재무정보\|원화환산 재무정보\|원화
  표시 재무정보" raw_report --include="*.xml"`) 완료(2026-08-15 추가 세션) — NAS·SD카드
  (dart_data) 양쪽 독립 스캔 결과 일치, 문자열 매치 5개사. 이후 `corporations`·
  `face_audit` DB 대조 + 원문(회사개황·종목코드·기능통화 주석) 대조로 4개사가 유니버스
  밖(외국기업 제외 대상)임을 확인 — 최종 Gate B 대상은 두산밥캣 1개사(§2-A 표).
