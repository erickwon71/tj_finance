# 설계 — `face_audit.py` NI 귀속 스킵게이트 결함 수정 (247건 스코프 확정, 2026-08-26 작성)

> 배경: R45(`docs/PARSING_RULES.md` 부록C, 메모리 `gateb-r44-resolve-redesign-2026-08-25`)
> Gate B 재감사 중 발견된 01137383(카카오게임즈) 2024Q3 예외 1건의 후속 조사.
> **이 문서는 설계만 담는다 — 구현은 사용자 승인 후 별도 착수.**

---

## 0. 요약

- **대상**: `face_audit.py` 독립 리더(source_version=v3)의 `is.controlling_ni` fail
  247건(fail_b 245 + fail_a 2, 전건 원문 XML 직접 실행 대조로 재분류 완료 — 추측 없음).
  `is.noncontrolling_ni`는 std_v3 컬럼 자체가 없어 대상에서 제외.
- **핵심 발견**: DB 값(db_won)은 이미 정답이고, `face_audit.py`의 독립 재추출값
  (report_won)만 틀렸다 — std_v3/combine.py 파이프라인은 무관, **감사기 자체의 결함**.
- **근본원인은 하나의 구조적 결함(스킵게이트)이 최소 2개 하위변종을 통해 발현**:
  - **① 스킵게이트 우선순위 오류(171건, 26개사)** — `_with_ni_attribution_text_fallback()`
    이 "이미 있으면 안 부른다" 정책이라, 일반 라벨매퍼(`account_mapper.map()`)가 먼저
    (변종에 따라 서로 다른 경로로) 오답을 채우면 섹션구조를 정확히 아는
    `_ni_attribution_text_candidates()`가 아예 호출되지 않는다.
  - **② TE/TD 구조함수 사각지대(70건, 01137383 포함)** — 정답 행이 `<TE>` 태그(ACODE
    없음)로 렌더링된 문서는 TE 전용 구조함수(ACODE 필수)와 TD 전용 구조함수(TE 있는
    행은 자매함수가 처리했다고 가정하고 건너뜀) **양쪽 다에서 빠진다** — ①과 무관한
    별개 결함, 스킵게이트를 고쳐도 안 풀린다.
- **설계 원칙**: 기존 R24/R25/R35/R45가 지켜온 "후보를 고르지 않고 넓히기만 한다"는
  단조성 계약을 이번에도 유지한다 — 다만 ①은 "넓히기"만으론 부족하고, **구조인식
  함수의 우선순위를 일반매퍼보다 앞에 두는 정책 역전**이 필요하다(아래 §2-A 근거).

---

## 1. 근본원인 상세 (247건 전수 원문 실행 대조, 2026-08-26)

### 1-0. 스코프 확정 방법론

`scripts/probe_faceaudit_ni_oci_mislabel_2026-08-26.py` — 247건 각각에 대해:
1. `std_financials_v3.source_rcepts`로 IS rcept 확인 → `download_tasks.file_path`
   (NAS 심링크)를 SD카드 미러(`/Volumes/dart_data/raw_report`, [[feedback-bulk-read-use-sdcard]])
   경로로 재작성해 원문 XML 확보.
2. 실제 프로덕션 리더 `read_report_face_tracked()`를 그대로 실행해 report_won 재현 여부 확인.
3. 구조인식 함수 `_ni_attribution_text_candidates()`를 **단독 실행**해 db_won을
   찾아낼 수 있는지(=스킵게이트만 없었다면 복구 가능했는지) 확인.
4. 넷 다 만족(재현O + 구조함수 단독성공O + db_won이 프로덕션 후보엔 없음)해야만
   "CONFIRMED_PATTERN" — 그 외는 미분류로 남긴다(짐작 금지, [[feedback-verify-against-source]]).

| 분류 | 건수 | gate_status |
|---|---:|---|
| CONFIRMED_PATTERN | **171 (26개사)** | 전부 fail_b |
| REPRODUCED_BUT_STRUCT_FUNC_ALSO_MISSES | **70** | fail_b 68 + **fail_a 2**(00201432 2025Q1, 00124504 2025FY) + 01137383 |
| NOT_REPRODUCED | 4 | fail_b(재실행 값이 DB 기록과 다름 — 파일 변경 가능성, 이 결함과 무관, 별도 확인 필요) |
| NO_XML_FILE | 2 | fail_b(이 프로브의 파일해석 한계, 미확인) |

### 1-A. ① 스킵게이트 우선순위 오류 — 171건, 최소 2개 하위변종 확인

`fin2/audit/face_audit.py::_with_ni_attribution_text_fallback()`(667줄):

```python
if "is.controlling_ni" in have and "is.noncontrolling_ni" in have:
    return lines   # 있으면 구조인식 함수를 아예 안 부름
```

`have`는 이미 확정된 Track A/B 라인의 canonical 집합인데, **정답인지 오답인지 안 가리고
"있다"는 사실만 본다.** 아래 두 변종 모두 이 게이트를 통해 정답 후보의 진입 자체를 막는다.

**변종 A — 트레일링 마침표가 bare 라벨 가드를 뚫음** (00913689 세경하이테크 2021H1
원문대조 확정, db_won=1,172,143,196 / report_won=978,887,585):

`account_mapper.py`의 "bare 지배지분 가드"(211~227줄)는
`normalized.endswith("지분")`으로 판정하는데, 이 문서의 총포괄손익 귀속 행 라벨이
`"지배기업 소유주지분."`(끝에 마침표, EUC-KR 문서의 필자 관행)이라 `endswith` 체크가
실패 — 가드를 그대로 통과해 fuzzy로 `is.controlling_ni`(신뢰도 0.93)에 오매핑된다.
실측:
```
'지배기업  소유주지분'   -> unknown.지배기업소유주지분 0.0   (정상 차단)
'지배기업 소유주지분.'   -> is.controlling_ni 0.93         ← 마침표 하나로 우회
```
바로 위 "당기순이익(손실)의 귀속" 섹션에 있는 진짜 정답(`"지배기업  소유주지분"`,
bare, 정상 차단됨)은 구조함수만이 찾을 수 있는데 스킵게이트에 막힌다.

**변종 B — "…지분순이익"류 라벨 자체가 무가드 alias** (01137383 카카오게임즈 2024Q3,
00117027 알루코 2011FY 등 원문대조 확정):

`"지배주주지분순이익(손실)"`/`"지배회사지분순이익"`처럼 "포괄"/"중단"/"계속영업"
리터럴이 전혀 없는 라벨은 기존 가드(187~278줄) 어디에도 안 걸리고 정상 alias로
통과한다 — 총포괄손익 귀속 섹션의 행인데도 라벨 텍스트만으론 원천적으로 구분 불가.
부수 발견(알루코): `"지배회사지분순이익"`은 fuzzy로 **`is.noncontrolling_ni`**(0.88)에
오매핑되기도 함 — 방향까지 틀리는 사례, 이 문서 스코프(controlling_ni) 밖이지만
같은 계열 결함이 noncontrolling_ni 쪽에도 존재할 가능성을 시사한다(미조치, 별도 트랙).
또한 `"지배기업소유주지분 합계"`(자본총계 항목, BS 개념)가 `is.controlling_ni`(IS
개념)에 fuzzy 매핑(0.91)되는 것도 확인 — 라벨이 손익 개념이 아닌데도 매핑되는
제3의 하위패턴으로 별도 조사가 필요하다(오늘 스코프 밖으로 분리).

### 1-B. ② TE/TD 구조함수 사각지대 — 70건(01137383 포함)

01137383 2024Q3 원문대조: "당기순이익의 귀속" 섹션의 정답 행(`지배주주지분`
= -12,526,674,618)이 `<TE>` 태그로 렌더링돼 있으나 **ACODE 속성이 없다**(문서
전체가 진짜 `ifrs-full_`/`dart_` XBRL 미태깅 — DART 내부 서식코드만 존재).

- TE 전용 구조함수 `_ni_attribution_structural_candidates()`(278줄)는
  `value_tes = [te for te in tes[1:] if te.get("ACODE") and te.get("ACONTEXT")]`로
  값 셀에 ACODE를 요구 — 이 행은 걸러져 후보를 못 낸다(직접 실행 확인, 0건).
- TD 전용 구조함수 `_ni_attribution_text_candidates()`(417줄)는
  `for tr in tbl.findall(".//TR"): if tr.findall("TE"): continue`로 **TE가 하나라도
  있는 행은 자매함수가 처리했다고 가정하고 건너뛴다** — 그 가정이 "TE=ACODE 있음"을
  전제하는데 이 문서는 성립하지 않는다.

결과: 정답이 TE/TD 어느 구조함수에도 안 걸리는 사각지대. **①(스킵게이트)을 고쳐도
이 70건은 안 풀린다** — 구조함수 자체가 처음부터 정답을 못 찾기 때문.

---

## 2. 제안 설계

### 2-A. ① 스킵게이트 정책 역전 — 구조인식 함수를 먼저 신뢰

**현재**: 일반매퍼(Track A/B) 결과 → "있으면" 스킵 → 구조함수는 최후 폴백.

**제안**: `is.controlling_ni`/`is.noncontrolling_ni` 두 canonical에 한해, **구조함수를
먼저 실행**하고, 그 결과가 있으면 그걸 신뢰(일반매퍼가 같은 canonical에 낸 값은
버리지 않고 병합 — 기존 "넓히기만" 원칙 유지, `audit_fields()`의 "후보 집합 어디든
일치하면 PASS" 판정과 동형), 구조함수가 **아무것도 못 찾을 때만** 일반매퍼 결과에
의존한다. `fin2/layer3/combine.py`의 R45(§B 앵커를 EBT−tax보다 먼저 단독 시도,
매치 없을 때만 폴백)와 정확히 같은 형태의 "순차 우선순위" 패턴 — 이 코드베이스에
이미 선례가 있는 설계다.

- **왜 "넓히기만"으론 부족한가**: 이 결함은 오답 후보가 정답 후보를 밀어내는 게
  아니라, 오답 후보의 **존재 자체가 정답 후보의 탐색 시도를 막는 것**(스킵게이트가
  "찾아볼지 말지"를 결정)이라 순서를 바꿔야 한다. 넓히기만으론 오답 후보가 여전히
  `have`에 먼저 들어가 게이트를 잠근다.
- **왜 안전한가**: 구조함수(`_ni_attribution_text_candidates`)는 섹션 헤더("...의
  귀속" vs "포괄")와 지배/비지배 정확히 1개씩이라는 좁고 검증된 조건에서만 값을
  내고, 모호하면 침묵한다(짐작 금지 원칙 내장, R35/R36 설계 그대로). 순서를
  바꿔도 새로운 "틀린 확신"을 만들 위험이 낮다 — 오히려 지금처럼 일반매퍼의
  넓은 라벨 유사도 매칭이 먼저 이기는 쪽이 더 위험하다는 게 이번 조사의 핵심 발견.
- **성능 영향**: `_with_ni_attribution_text_fallback()`은 이미 이 두 canonical
  전용의 좁은 스코프 함수라 항상 호출해도 `_detect_body_statement_tables()`
  재파싱 비용 자체는 변하지 않는다(현재도 "없을 때만" 호출하던 걸 "먼저" 호출하는
  것으로 바뀔 뿐 — 오히려 매번 호출되므로 빈도는 늘어난다. 대량 재감사 시 실측
  필요, §4 참고).

### 2-B. ② TE/TD 사각지대 — TD 함수의 "TE 있으면 skip" 전제 재검토

**제안 방향(미확정, 사용자 결정 필요)**: TD 전용 구조함수(`_ni_attribution_text_candidates`)
의 스킵 조건을 "TE가 있으면 skip"에서 "**ACODE 있는 TE가 있으면** skip"으로
좁힌다 — ACODE 없는 `<TE>`는 사실상 `<TD>`와 동등(값 파싱 로직도 이미 `_cell_text`
공용)하므로, 그 경우엔 TD 함수가 대신 처리하게 한다.

- **확인 필요 사항(구현 전)**: 이 변경이 겨냥하는 "TE인데 ACODE 없음" 행이 TD
  함수의 나머지 로직(`tr.findall("TD")` 기반 셀 추출)과 호환되는지 — 현재 TD
  함수는 `tds = tr.findall("TD")`로 셀을 뽑으므로, TE 태그인 행은 이 라인에서
  `len(tds) < 2`로 걸려 건너뛰어질 것이다(TE와 TD는 별개 태그명). 즉 스킵 조건만
  바꿔서는 안 되고, 셀 추출도 `tr.findall("TD") or tr.findall("TE")` 식으로 같이
  확장해야 한다 — **미착수, 원문 표본으로 부작용(진짜 ACODE 태깅 문서에서 중복
  카운트 등) 재검증 필요**.

---

## 3. 영향범위 (예상, 재검증 전제)

| 수정 | 대상 | 예상 효과 |
|---|---:|---|
| §2-A(스킵게이트 역전) | 171건(26개사) | fail_b → pass 전환 예상(구조함수가 이미 단독 실행에서 db_won 확인됨) |
| §2-B(TE/TD 사각지대) | 70건(01137383, fail_a 2건 포함) | 구현 전이라 효과 미검증 — §2-B 자체가 미확정 설계 |
| 미조치(오늘 스코프 밖) | noncontrolling_ni 방향성 오매핑(알루코 사례), BS "합계"→IS 오매핑 | 별도 트랙 필요, 이 문서에서 다루지 않음 |
| 미조치 | NOT_REPRODUCED 4건, NO_XML_FILE 2건 | 이 결함과 무관/미확인 — 개별 확인 필요 |

---

## 4. 검증 계획 (구현 후, 미착수)

1. `scripts/probe_faceaudit_ni_oci_mislabel_2026-08-26.py`를 수정 후 코드로 재실행 —
   171건 전부 CONFIRMED_PATTERN → (구조함수가 db_won을 내는) pass로 전환되는지 재확인.
2. Gate B 표본 재감사(`scripts/gateb_audit.py --source v3 --recheck --corp-file
   <247건 corp 목록>`)로 fail_a 회귀 0건 확인(R44/R45와 동일한 검증 관례).
3. §2-A 성능 영향 실측(대량 재감사 러닝타임 비교, 호출 빈도 변화가 유의미한지).
4. §2-B는 설계 자체가 미확정이므로, 구현 승인 전 원문 표본(TE-無ACODE 문서 vs
   진짜 ACODE 문서)으로 부작용 여부 먼저 확인.

---

## 5. 결정 필요 사항

- [ ] §2-A(스킵게이트 역전) 구현 승인 여부
- [ ] §2-B(TE/TD 사각지대) 설계를 이 트랙에서 같이 다룰지, 별도 트랙으로 분리할지
- [ ] 부수 발견(noncontrolling_ni 방향성 오매핑, BS→IS 오매핑) 별도 트랙 개설 여부
- [ ] NOT_REPRODUCED 4건 개별 조사 여부(우선순위 낮음 표시)

관련 코드: `fin2/audit/face_audit.py`(`_with_ni_attribution_text_fallback`·
`_ni_attribution_text_candidates`·`_ni_attribution_structural_candidates`) ·
`parser/common/account_mapper.py`(187~278줄, bare/포괄 가드) · 스크립트
`scripts/probe_faceaudit_ni_oci_mislabel_2026-08-26.py`. 배경 메모리
`gateb-r44-resolve-redesign-2026-08-25`, `docs/PARSING_RULES.md` 부록C.
