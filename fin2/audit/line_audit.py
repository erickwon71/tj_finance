"""
Gate B Phase B — 보고서 본문 **전 계정 라인** 전수 대조 (PRD 04 §1·§2 원안).

Phase A(`face_audit.audit_std_row`)는 std_v3 의 25개 표준 필드만 보고서 face 와 대조한다.
Phase B 는 그 바깥의 소계·기타 계정을 포함한 **보고서 본문 전 face 라인**을 계층2 원천
(`report_lines`)과 **라벨 기반**으로 1:1 대조한다.

★2026-09-01 계층2 GC §4-3 이식(설계 `docs/plans/gateb_phaseb_line_audit_v3_migration_design_
2026-09-01.md`, Option 2) — 감사 DB 측을 `fact_v2`(곧 DROP 예정, 55GB)에서 `report_lines`
(계층3이 실제로 읽는 원천)로 옮겼다. 핵심 변화:
  - 매칭 키가 `(acode, basis, is_cumulative)`(XBRL 태그 동일성)에서
    `(basis, 정규화(row_label), is_cumulative)`(라벨 동일성)로 바뀌었다 — `report_lines` 에는
    acode 개념 자체가 없기 때문(§3-2 실측, `report_lines.label_raw` 만 있음).
  - Track A(XBRL)·Track B(텍스트)가 이제 **같은 라벨 매칭 메커니즘**을 쓴다(설계 §5 옵션(b)).
    유일한 실질 차이는 매칭 방향성 — Track A 는 face→DB 1:1(양쪽 다 특정 shape 를 갖는 표준
    XBRL 컨텍스트), Track B 는 DB→face 값-집합 포함(any-column 텍스트 리더가 같은 라벨로
    당기·비교연도 등 여러 리터럴을 만들어내므로 위치 대응이 아니라 집합 소속으로 판정) —
    아래 각 함수 docstring 참고.
  - 주당/EPS·주식수 계열은 감사 리더(`read_report_face_xbrl`)가 문서 기본단위를 셀에
    그대로 적용해 버리는 알려진 버그(원/주인데 배수 환산)로 오탐의 64%를 차지해(§3-3 실측)
    `_track_a_face()` 에서 명시 제외한다(§ EPS_EXCLUDE_RE 근처 주석).

정책(사용자 확정, 유지):
  - **본문 전수·라벨 정확대조**: `in_body_section is not False`(True 또는 판정불가 통과,
    False 만 배제 — 결측>오탐) 라인만. 주석표는 대상 아님(Phase 1.5 실측 근거).
  - **측정 우선**: `VALUE_DIFF`(report_lines 행 존재, won 불일치 = 실제 손상)만 차단 후보
    (fail_a). `MISSING_IN_DB`(보고서엔 있으나 report_lines 부재)는 완전성 지표로 기록만
    (차단 안 함).

★설계 불변식(설계문서 §4 리스크 3, 반드시 지킬 것) — 감사 리더(`face_audit.py:
read_report_face_xbrl`/`read_report_face_text`)는 `TE[@ACODE]`/`ACONTEXT` 원문 태그에서
basis·기간·라벨을 **직접** 얻고, `report_lines` 는 표 렌더링 파이프라인(열 선택·단위=열 판정·
섹션 경계·선두 None 절삭 등 R-규칙)으로 얻는다. 이 둘이 **같은 코드를 재사용하지 않는다는
독립성**이 이 감사의 전부다(둘 다 같은 문서를 보되 서로 다른 경로로 읽어야 교차검증이 성립).
이 모듈이 `fin2/extract/report_lines.py` 의 렌더링 함수를 import 하는 일은 절대 없어야 한다
(간접 포함도 안 됨) — 이미 그렇고, 앞으로도 그래야 한다.

이 모듈은 순수 함수(DB/IO 없음) — 입력은 이미 읽은 face 라인 + `report_lines` 행(dict).
독립성·테스트 용이. `report_lines` 조회 자체(SQL)는 `scripts/gateb_audit.py::audit_lines()`
소관(Phase 3 배선).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from fin2.audit.face_audit import _XBRL_PREFIXES, _normalize_ws, _statement_of, FaceLine

# 라인 불일치 사유
REASON_VALUE_DIFF = "VALUE_DIFF"      # report_lines 행 존재, won 불일치 — 차단 후보(추출 손상)
REASON_MISSING = "MISSING_IN_DB"      # 보고서 face 라인이 report_lines 에 없음 — 완전성 지표
REASON_EXTRA = "EXTRA_IN_DB"          # report_lines 본문 행이 보고서 face 에 없음 — 감사 reader 갭 지표

# ★§3-3 실측(2026-09-01) — 감사 리더가 EPS/주식수 셀에 문서 기본단위 ADECIMAL 을 그대로
# 적용해(원/주·주 는 배수환산 대상이 아닌데) 오탐의 64%(57,368/89,660줄)를 차지하던 계열.
# `report_lines.py` 는 이미 R28(`_emit_eps_lines`)로 이 문제를 따로 처리해 정답을 저장한다 —
# 즉 **추출은 고쳐졌는데 감사 리더만 안 고쳐진 상태**(리더 쪽 실제 수정은 범위 밖, 설계문서
# §8). Track A 감사 대상에서만 제외한다(리더 자체는 손대지 않음 — Phase A 회귀 위험 분리).
_PER_SHARE_ACODE_RE = re.compile(r"PerShare|NumberOfShares", re.IGNORECASE)


@dataclass
class LineAudit:
    """한 보고서 라인(또는 잉여 report_lines 행)의 대조 결과."""
    label: str                    # 정규화 라벨(매칭 키) — report_lines.label_raw 와 대조된 값
    basis: str | None
    statement: str | None
    report_won: int | None
    db_won: int | None
    match: bool
    reason: str | None            # None=match / VALUE_DIFF / MISSING_IN_DB / EXTRA_IN_DB
    acode: str | None = None      # Track A 진단용 — face 쪽 XBRL ACODE(매칭 키 아님, 트리아지용)
    canonical: str | None = None  # Track B 진단용 — face 쪽 매핑된 canonical(매칭 키 아님)


@dataclass
class ReportLineAudit:
    """rcept 단위 라인감사 롤업."""
    rcept_no: str
    n_lines: int = 0
    n_match: int = 0
    n_value_diff: int = 0
    n_missing: int = 0
    n_extra: int = 0
    value_diffs: list[LineAudit] = field(default_factory=list)   # 차단 후보 상세
    missing: list[LineAudit] = field(default_factory=list)       # 완전성 지표 상세

    @property
    def line_gate_status(self) -> str:
        """value_diff>0 → fail_a(손상 후보), 그 외 → pass. Track A/B 공통(호출자가 등급대상 판정)."""
        return "fail_a" if self.n_value_diff else "pass"


def won_match(a: int, b: int, adecimal: int | None, *, allow_sign: bool = False) -> bool:
    """
    won 동치 판정 — 표시단위 ±1 허용(발행사 자체 반올림·파생필드 라운딩). Phase A `audit_fields`
    와 동일 규약. 라인 대조는 **리터럴 셀↔추출값**이라 부호도 같아야 정상 → 기본 부호 엄격
    (allow_sign=True 면 부호반대도 허용; 라인감사 기본 미사용).
    """
    tol = 10 ** (-adecimal) if (adecimal or 0) < 0 else 1
    if abs(a - b) <= tol:
        return True
    return allow_sign and abs(a + b) <= tol


def _track_a_face(face_lines: list[FaceLine]) -> list[FaceLine]:
    """face 라인 중 **본문(face) Track A 라인**만:
      - acode 가 XBRL 접두(ifrs-full_/dart_) — 텍스트 보충 라인(acode=라벨)·엔티티 확장(UDF)
        매입채무 라벨폴백 라인을 자연 제외. ★매칭 키에는 더 이상 acode 를 안 쓰지만
        (report_lines 에 acode 개념이 없음), 이 필터 자체는 "read_report_face_xbrl() 이
        실제로 읽은 XBRL 리터럴 셀인가"를 가리는 용도로 그대로 유지한다.
      - EPS/주식수 계열(acode 정규식) 제외 — §3-3 실측 오탐 64% 클러스터(모듈 상단 주석).
      - basis 명시(consolidated/separate) — basis=None 은 **주석 컨텍스트**(세그먼트·
        특수관계자·담보 등 다중 셀이 동일 표준태그 재사용) → 본문 아님.
      - row_label 확보(Phase 1) — 매칭 키의 필수 성분. 없는 라인(레이아웃 이례로 라벨 셀을
        못 찾은 경우, `_row_label_text` 참고)은 대조 불가 → 배제.
      - in_body_section 이 False 가 아님(True 또는 None 통과) — Phase 1.5(2026-09-01,
        게이트1 88.20%→100.00%). None=판정 시도 안 함(결측>오탐, 배제하지 않음), False 만
        주석표 확정 신호라 배제."""
    return [ln for ln in face_lines
            if ln.acode.startswith(_XBRL_PREFIXES) and not _PER_SHARE_ACODE_RE.search(ln.acode)
            and ln.amount_won is not None and ln.basis is not None
            and ln.row_label and ln.in_body_section is not False]


def _track_a_key(basis: str | None, label: str | None, is_cumulative: bool) -> tuple:
    """Track A 매칭 키 = (basis, 정규화 라벨, is_cumulative). is_cumulative 은 XBRL
    ACONTEXT 가 실제로 태깅하는 반기/3분기 누적(YTD) 축이라 그대로 키에 포함한다(같은
    (basis,라벨)에 누적·3개월 셀이 공존할 수 있음 — 구 acode 키 시절과 동일 근거)."""
    return (basis, _normalize_ws(label) if label else None, bool(is_cumulative))


def reconcile_report_lines(
    rcept_no: str,
    face_lines: list[FaceLine],
    line_rows: list[dict],
) -> ReportLineAudit:
    """
    한 보고서의 Track A(XBRL) 전 face 라인을 `report_lines` 본문 행과 라벨 기반 1:1 대조.

    face_lines : `read_report_face_xbrl(fp)` 결과(col0·비차원). 내부에서 Track A 라인만 필터.
    line_rows  : `report_lines` WHERE rcept_no=? AND col_index=0 의 행. 각 dict 는
                 {label_raw, basis, is_cumulative, value_won, statement} 키를 가진다.

    매칭 키 = (basis, 정규화(row_label), is_cumulative). ★statement 는 키에서 뺐다 — 게이트1
    실측(2026-09-01)에서 Track A face 라인의 statement 상당수가 canonical 미매핑으로 None
    (BS 는 period_kind 로 보정되지만 IS/CF 는 보정 없음)이라 키에 넣으면 순수 라벨매칭
    품질을 오염시킨다는 것이 확인됐고, in_body_section 필터(Phase 1.5)만으로 게이트1
    100.00%(38,414/38,414)를 이미 달성했다 — 설계문서 §Phase2-1 이 적어둔 4성분 키
    (statement 포함)는 그 재측정 이전에 쓰인 초안이라, 실측으로 검증된 3성분 키로 대체한다.
    statement 는 LineAudit 의 진단용 필드로만 보존(가능하면 report_lines 쪽 값을 권위로,
    없으면 face 쪽 유도값으로 폴백).
    """
    out = ReportLineAudit(rcept_no=rcept_no)

    # report_lines 인덱스: 키당 1행(동률 라벨 충돌 시 첫 등장이 대표 — 구 acode 키 시절
    # coarse 키 충돌 처리와 동일한 first-wins 규약, §4 리스크 문서화된 잔여 한계).
    # basis=None(주석 컨텍스트) 행은 본문 대조 대상 아님 → 제외(face 측 _track_a_face 와
    # 대칭, extra 오집계 방지 — 구 acode 키 시절과 동일 근거).
    line_idx: dict[tuple, dict] = {}
    for r in line_rows:
        label = r.get("label_raw")
        if r.get("value_won") is None or not label or r.get("basis") is None:
            continue
        key = _track_a_key(r.get("basis"), label, r.get("is_cumulative"))
        line_idx.setdefault(key, r)

    face_keys: set[tuple] = set()   # face 에 등장한 전 키(match·value_diff 무관) → extra 판정용
    for ln in _track_a_face(face_lines):
        out.n_lines += 1
        key = _track_a_key(ln.basis, ln.row_label, ln.is_cumulative)
        face_keys.add(key)
        lr = line_idx.get(key)
        if lr is None:
            stmt = ln.statement or _statement_of(ln.canonical)
            out.n_missing += 1
            out.missing.append(LineAudit(
                label=key[1], basis=ln.basis, statement=stmt,
                report_won=ln.amount_won, db_won=None, match=False,
                reason=REASON_MISSING, acode=ln.acode))
            continue
        stmt = lr.get("statement") or ln.statement or _statement_of(ln.canonical)
        db_won = lr["value_won"]
        if won_match(ln.amount_won, db_won, ln.adecimal):
            out.n_match += 1
        else:
            out.n_value_diff += 1
            out.value_diffs.append(LineAudit(
                label=key[1], basis=ln.basis, statement=stmt,
                report_won=ln.amount_won, db_won=db_won, match=False,
                reason=REASON_VALUE_DIFF, acode=ln.acode))

    # 역방향: report_lines 본문 행 중 보고서 face 에 아예 없던 키 → EXTRA(감사 reader 커버
    # 갭 지표). ★report_lines 는 XBRL ACODE 유무와 무관하게 본문 표의 전 행(구조행 포함)을
    # 담으므로, fact_v2 시절보다 EXTRA 가 늘어날 수 있다(ACODE 없이 렌더링만 되는 소계 행 등)
    # — 이건 신호 성격 변화지 버그가 아니다(Phase 4-5 트리아지에서 해석).
    out.n_extra = sum(1 for key in line_idx if key not in face_keys)
    return out


def _track_b_face(face_lines: list[FaceLine]) -> list[FaceLine]:
    """Track B(텍스트) 본문 face 라인만: **매핑된 canonical** + 비XBRL acode(라벨) +
    won/basis 존재. `read_report_face_text()` 는 매핑 라인만 방출하므로 canonical 이 항상
    존재. ★`.label` 은 Track A 와 달리 이미 "값 셀 텍스트"가 아니라 **계정 라벨 원문**이다
    (`read_report_face_text()` 의 `label=label[:80]`, 라벨 셀 자체를 그대로 담음) — 그래서
    Track B 는 Track A 의 `row_label` 같은 별도 필드가 필요 없다."""
    return [ln for ln in face_lines
            if ln.canonical and not ln.acode.startswith(_XBRL_PREFIXES)
            and ln.amount_won is not None and ln.basis is not None]


def _track_b_key(basis: str | None, label: str | None) -> tuple:
    """Track B 매칭 키 = (basis, 정규화 라벨). ★is_cumulative 를 의도적으로 뺐다 —
    `read_report_face_text()` 는 이 필드를 실제 축이 아니라 "interim 필터 통과용" 고정값
    True 로 채운다(구 코드부터 그랬음, `face_audit.py::_read_table` 참고). 키에 넣으면
    report_lines 쪽 실제 is_cumulative(BS=False 등)와 상시 불일치해 전량 MISSING 이 된다 —
    구 canonical 키 시절에도 이 필드는 키에 없었다(동작 보존)."""
    return (basis, _normalize_ws(label) if label else None)


def reconcile_report_lines_text(
    rcept_no: str,
    face_lines: list[FaceLine],
    line_rows: list[dict],
) -> ReportLineAudit:
    """
    Track B(텍스트) 보고서 face 라인을 `report_lines` 본문 행과 **라벨 기반 값-집합** 대조.

    ★2026-09-01 Option 2 §5(b) 채택 — canonical 값-집합 대조(구 fact_v2 방식)를 버리고
    Track A 와 같은 (basis, 정규화 라벨) 매칭으로 통일했다. `report_lines` 엔 canonical
    개념이 아예 없어(§3-2 실측) canonical 기반 대조는 애초에 재현 불가능했고, 라벨로
    통일하면 A/B 두 메커니즘을 하나로 유지보수할 수 있다.

    ★방향성은 구 Track B 를 그대로 보존한다(라벨만 바뀜) — `read_report_face_text()` 는
    독립 리더로서 본문 표의 **모든 컬럼(당기+비교연도)** 리터럴을 읽으므로, 같은 라벨로
    여러 FaceLine(서로 다른 값)이 나온다. 그래서 위치 대응(1:1)이 아니라 Phase A
    (`audit_std_row`)의 검증된 방향 — **report_lines(당기 col0=권위값)가 보고서 라벨의
    값-집합에 존재하는가** — 로 판정한다(당기+비교 포함 집합이라 정상 당기값은 포함):
      - MISSING : report_lines 의 (basis,라벨)을 리더가 보고서에서 못 찾음(리더 커버 갭 지표).
      - VALUE_DIFF: (basis,라벨)은 보고서에 있으나 report_lines 당기값이 **어느 컬럼에도**
        없음 → 다른 표/단위 오선택 등 추출 손상 후보(차단 후보).
      - match   : report_lines 당기값이 보고서 값-집합에 존재.
    EXTRA 는 여전히 비대상 — `read_report_face_text()` 는 canonical 매핑에 성공한 라인만
    방출하므로(미매핑 라벨·소계 등은 절대 안 나옴) 역방향(report_lines 쪽 잉여)을 재면
    "리더가 원래 안 보는 라벨"이 전부 EXTRA 로 잡혀 무의미하다(구 판단 유지).

    line_rows: `report_lines` WHERE rcept_no=? AND col_index=0 의 행. {label_raw, basis,
               is_cumulative, value_won, statement} 키 필요.
    """
    out = ReportLineAudit(rcept_no=rcept_no)

    # 보고서 값-집합: (basis, 정규화 라벨) → [won, ...] (전 컬럼 리터럴 = 당기+비교연도 포함)
    rep_vals: dict[tuple, list[int]] = {}
    rep_repr: dict[tuple, FaceLine] = {}   # 대표 라인(진단용 canonical/adecimal) — 최초 등장
    for ln in _track_b_face(face_lines):
        key = _track_b_key(ln.basis, ln.label)
        rep_vals.setdefault(key, []).append(ln.amount_won)
        rep_repr.setdefault(key, ln)

    for r in line_rows:
        label = r.get("label_raw")
        if r.get("value_won") is None or not label or r.get("basis") is None:
            continue
        out.n_lines += 1
        key = _track_b_key(r.get("basis"), label)
        db_won = r["value_won"]
        reps = rep_vals.get(key)
        repr_ln = rep_repr.get(key)
        stmt = r.get("statement")
        canon = repr_ln.canonical if repr_ln else None
        if not reps:
            out.n_missing += 1
            out.missing.append(LineAudit(
                label=key[1], basis=r.get("basis"), statement=stmt,
                report_won=None, db_won=db_won, match=False,
                reason=REASON_MISSING, canonical=canon))
            continue
        adecimal = repr_ln.adecimal if repr_ln else None
        if any(won_match(db_won, rw, adecimal) for rw in reps):
            out.n_match += 1
        else:
            out.n_value_diff += 1
            out.value_diffs.append(LineAudit(
                label=key[1], basis=r.get("basis"), statement=stmt,
                report_won=reps[0], db_won=db_won, match=False,
                reason=REASON_VALUE_DIFF, canonical=canon))
    return out
