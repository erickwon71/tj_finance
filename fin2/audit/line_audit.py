"""
Gate B Phase B — 보고서 본문 **전 계정 라인** 전수 대조 (PRD 04 §1·§2 원안).

Phase A(`face_audit.audit_std_row`)는 std_v2 의 25개 표준 필드만 보고서 face 와 대조한다.
Phase B 는 그 바깥의 소계·기타 계정을 포함한 **보고서 Track A(XBRL) 전 face 라인**을 추출된
전 셀(`fact_v2`)과 acode 정확매칭으로 1:1 대조한다.

정책(사용자 확정):
  - **Track A 전수·정확대조만**: XBRL 비차원 col0 `TE[@ACODE]` 라인. acode 가 권위(ADECIMAL)라
    won-공간 동치 비교가 정확. Track B/C(텍스트·PDF)는 acode 부재 → 본 단계 비대상.
  - **측정 우선**: `VALUE_DIFF`(fact_v2 행 존재, won 불일치 = 실제 손상)만 차단 후보(fail_a).
    `MISSING_IN_DB`(보고서엔 있으나 fact_v2 부재)는 완전성 지표로 기록만(차단 안 함).

이 모듈은 순수 함수(DB/IO 없음) — 입력은 이미 읽은 face 라인 + fact 행. 독립성·테스트 용이.

★ `fact_v2` 커버리지 참고(2026-08-09 갱신) — `fact_v2`는 신규 XBRL 원문 파서(2026-08-06 완료)가
  채우는 중이라 **일부 rcept에만 행이 있다**(당시 2,956개 rcept / 1,451,930행 — 전체 대상의
  ~2.4%). `fact_v2`에 행이 없는 rcept는 `n_missing`이 전량으로 나오지만 `line_gate_status`는
  `n_value_diff`(실제 값 불일치)만 보므로 **fail_a로 차단되지는 않는다** — `MISSING_IN_DB`는
  여전히 "완전성 지표"일 뿐 결함 신호가 아니다. 다만 이 지표를 **전수 완전성 판단**에 쓰려면
  fact_v2 커버리지가 낮은 동안은 "대다수 missing"이 정상이라는 걸 감안할 것 — 커버리지가
  넓어지는 대로 이 숫자의 의미도 자동으로 개선된다(코드 변경 불필요).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fin2.audit.face_audit import _XBRL_PREFIXES, _statement_of, FaceLine

# 라인 불일치 사유
REASON_VALUE_DIFF = "VALUE_DIFF"      # fact_v2 행 존재, won 불일치 — 차단 후보(추출 손상)
REASON_MISSING = "MISSING_IN_DB"      # 보고서 face 라인이 fact_v2 에 없음 — 완전성 지표
REASON_EXTRA = "EXTRA_IN_DB"          # fact_v2 col0 행이 보고서 face 에 없음 — 감사 reader 갭 지표


@dataclass
class LineAudit:
    """한 보고서 라인(또는 잉여 fact 행)의 대조 결과."""
    acode: str
    basis: str | None
    statement: str | None
    label: str
    report_won: int | None
    db_won: int | None
    match: bool
    reason: str | None          # None=match / VALUE_DIFF / MISSING_IN_DB / EXTRA_IN_DB


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
      - acode 가 XBRL 접두(ifrs-full_/dart_) — 텍스트 보충 라인(acode=라벨) 자연 제외.
      - basis 명시(consolidated/separate) — DART K-IFRS XBRL 은 본문 BS/IS/CF 셀에 항상
        연결/별도 시나리오를 태깅한다. basis=None 은 **주석 컨텍스트**(세그먼트·특수관계자·
        담보 등 다중 셀이 동일 표준태그 재사용) → 본문 아님(PRD 04 = 본문 face, 주석은 2단계).
        coarse 키 (acode,basis,is_cumulative) 가 주석 다중셀에서 충돌해 false VALUE_DIFF 유발 →
        본문(basis 태깅) 으로 한정해 정밀도 확보."""
    return [ln for ln in face_lines
            if ln.acode.startswith(_XBRL_PREFIXES) and ln.amount_won is not None
            and ln.basis is not None]


def reconcile_report_lines(
    rcept_no: str,
    face_lines: list[FaceLine],
    fact_rows: list[dict],
) -> ReportLineAudit:
    """
    한 보고서의 Track A 전 face 라인을 fact_v2 col0 비차원 행과 1:1 대조.

    face_lines : `read_report_face_xbrl(fp)` 결과(col0·비차원). 내부에서 Track A 접두만 필터.
    fact_rows  : `fact_v2` WHERE rcept_no=? AND col_index=0 AND NOT is_dimensional 의 행.
                 각 행은 {acode, basis, is_cumulative, adecimal, amount_won} 키를 가진 dict.

    매칭 키 = (acode, basis, is_cumulative). 보고서/추출 양쪽 동일 XBRL 셀에서 도출되므로 정확.
    """
    out = ReportLineAudit(rcept_no=rcept_no)

    # fact 인덱스: (acode, basis, is_cumulative) → 행. col0 비차원은 키당 1행(uq 보장).
    # basis=None(주석 컨텍스트) 행은 본문 대조 대상 아님 → 제외(face 측 _track_a_face 와 대칭,
    # extra 오집계 방지).
    fact_idx: dict[tuple, dict] = {}
    for r in fact_rows:
        if r.get("amount_won") is None or r.get("basis") is None:
            continue
        key = (r["acode"], r.get("basis"), bool(r.get("is_cumulative")))
        fact_idx.setdefault(key, r)

    face_keys: set[tuple] = set()   # face 에 등장한 전 키(match·value_diff 무관) → extra 판정용
    for ln in _track_a_face(face_lines):
        out.n_lines += 1
        key = (ln.acode, ln.basis, bool(ln.is_cumulative))
        face_keys.add(key)
        fr = fact_idx.get(key)
        stmt = ln.statement or _statement_of(ln.canonical)
        if fr is None:
            out.n_missing += 1
            out.missing.append(LineAudit(
                ln.acode, ln.basis, stmt, ln.label,
                ln.amount_won, None, False, REASON_MISSING))
            continue
        db_won = fr["amount_won"]
        if won_match(ln.amount_won, db_won, ln.adecimal):
            out.n_match += 1
        else:
            out.n_value_diff += 1
            out.value_diffs.append(LineAudit(
                ln.acode, ln.basis, stmt, ln.label,
                ln.amount_won, db_won, False, REASON_VALUE_DIFF))

    # 역방향: fact col0 행 중 보고서 face 에 아예 없던 키 → EXTRA(감사 reader 커버 갭, 지표).
    out.n_extra = sum(1 for key in fact_idx if key not in face_keys)
    return out


def _track_b_face(face_lines: list[FaceLine]) -> list[FaceLine]:
    """Track B(텍스트) 본문 face 라인만: **매핑된 canonical** + 비XBRL acode(라벨) +
    won/basis 존재. read_report_face_text 는 매핑 라인만 방출하므로 canonical 이 항상 존재."""
    return [ln for ln in face_lines
            if ln.canonical and not ln.acode.startswith(_XBRL_PREFIXES)
            and ln.amount_won is not None and ln.basis is not None]


def reconcile_report_lines_text(
    rcept_no: str,
    face_lines: list[FaceLine],
    fact_rows: list[dict],
) -> ReportLineAudit:
    """
    Track B(텍스트) 보고서 face 라인을 fact_v2(xml_text) 와 **(canonical, basis) 값-집합** 대조.

    Track A 와 달리 XBRL acode 가 없어(fact_v2 는 라벨을 acode 로 저장) 라벨은 발행사별
    표기·소계 중복으로 불안정한 키다. 또한 독립 리더(read_report_face_text)는 본문 표의
    **모든 컬럼(당기+비교연도)** 리터럴을 읽으므로, 보고서 측이 당기값만이 아니다.
    그래서 Phase A(audit_std_row) 의 검증된 방향 — **fact_v2(당기 col0=권위값)가 보고서
    canonical 값-집합에 존재하는가** — 로 판정한다(당기+비교 포함 집합이라 정상 당기값은 포함):
      - MISSING : fact_v2 의 (canonical,basis) 를 리더가 보고서에서 못 찾음(리더 커버 갭 지표).
      - VALUE_DIFF: (canonical,basis) 는 보고서에 있으나 fact_v2 당기값이 **어느 컬럼에도**
        없음 → 다른 표/단위 오선택 등 추출 손상 후보(차단 후보).
      - match   : fact_v2 당기값이 보고서 값-집합에 존재.
    EXTRA 는 비대상(리더는 매핑라인만, fact_v2 는 미매핑 보존 → 역방향 무의미).

    fact_rows: fact_v2 WHERE rcept_no=? AND col_index=0 AND NOT is_dimensional 의 행.
               각 dict 는 {canonical_account, basis, adecimal, amount_won} 키 필요.
    """
    out = ReportLineAudit(rcept_no=rcept_no)

    # 보고서 값-집합: (canonical, basis) → [won, ...] (전 컬럼 리터럴 = 당기+비교연도 포함)
    rep_idx: dict[tuple, list[int]] = {}
    for ln in _track_b_face(face_lines):
        rep_idx.setdefault((ln.canonical, ln.basis), []).append(ln.amount_won)

    for r in fact_rows:
        canon = r.get("canonical_account")
        if not canon or r.get("amount_won") is None or r.get("basis") is None:
            continue
        out.n_lines += 1
        db_won = r["amount_won"]
        reps = rep_idx.get((canon, r["basis"]))
        stmt = _statement_of(canon)
        if not reps:
            out.n_missing += 1
            out.missing.append(LineAudit(
                canon, r["basis"], stmt, canon,
                None, db_won, False, REASON_MISSING))
            continue
        if any(won_match(db_won, rw, r.get("adecimal")) for rw in reps):
            out.n_match += 1
        else:
            out.n_value_diff += 1
            out.value_diffs.append(LineAudit(
                canon, r["basis"], stmt, canon,
                reps[0], db_won, False, REASON_VALUE_DIFF))
    return out
