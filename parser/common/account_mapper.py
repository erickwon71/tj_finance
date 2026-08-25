"""
계정과목 표준화 매퍼 (3단계)

Stage 1: 정확 일치 (account_maps/*.py alias 사전)
Stage 2: 정규화(amount_normalizer.normalize_account_name) 후 일치
Stage 3: 퍼지 매핑 (jellyfish Jaro-Winkler ≥ 0.88 또는 포함 관계)

실패 시:
  account_code = "unknown.{정규화된_계정명}"
  → unknown_accounts DB 테이블에 집계 (추후 alias 추가 우선순위)

사용 예:
    mapper = AccountMapper()
    code, confidence = mapper.map("(1)현금및현금성자산 (주5,6)")
    # → ("bs.cash", 1.0)

    code, confidence = mapper.map("선급법인세")
    # → ("bs.current_tax_asset", 0.91)  또는  ("unknown.선급법인세", 0.0)
"""
import re
from dataclasses import dataclass
from typing import Optional

try:
    import jellyfish
    _HAS_JELLYFISH = True
except ImportError:
    _HAS_JELLYFISH = False

from account_maps.bs_accounts import BS_ACCOUNTS
from account_maps.is_accounts import IS_ACCOUNTS
from account_maps.cf_accounts import CF_ACCOUNTS
from account_maps.note_accounts import NOTE_ACCOUNTS
from parser.common.amount_normalizer import normalize_account_name


# 퍼지 오매핑 차단 라벨.
# ★ 2026-07-18: 현금및예적금 계열을 **여기서 뺐다**(사용자: '현금및예금 계열은 모두 같은
# 내용') → account_maps/bs_accounts.py 의 bs.cash exact alias 로 승급. 실측(2015+ 400건)에서
# 이 라벨은 0건이라 과대계상 우려가 무의미했다. 현재 이 집합은 비어 있으나, 향후 퍼지
# 오매핑이 확인되는 합산성 라벨을 여기에 추가하는 용도로 유지한다.
_FUZZY_BLOCK: set[str] = set()


@dataclass
class MappingResult:
    account_code: str          # 표준 코드 또는 "unknown.{name}"
    confidence: float          # 1.0=정확/포함, 0.88~0.99=퍼지, 0.0=실패
    stage: str                 # "exact" / "normalized" / "fuzzy" / "unknown"
    matched_alias: Optional[str] = None  # 실제로 매칭된 alias


class AccountMapper:
    """
    모든 계정과목 매핑 사전을 로드하고 3단계 매핑을 수행한다.
    """

    def __init__(self, fuzzy_threshold: float = 0.88):
        self.fuzzy_threshold = fuzzy_threshold
        self._exact: dict[str, str] = {}       # alias → code
        self._normalized: dict[str, str] = {}  # 정규화된 alias → code
        self._aliases_by_code: dict[str, list[str]] = {}  # code → alias 리스트

        self._build_index()

    def _build_index(self) -> None:
        """모든 account_maps를 병합해 검색 인덱스 생성.

        섹션별 우선순위: BS > IS > CF > NOTE
        단, 섹션 접두사(bs./is./cf./note.)가 같은 경우만 실제 사용되므로
        중복 alias는 섹션별로 별도 보관한다.
        """
        # 섹션별 인덱스 (fs_type prefix → {alias: code})
        self._exact_by_prefix: dict[str, dict[str, str]] = {
            "bs": {}, "is": {}, "cf": {}, "note": {},
        }
        self._normalized_by_prefix: dict[str, dict[str, str]] = {
            "bs": {}, "is": {}, "cf": {}, "note": {},
        }

        section_maps = [
            ("bs",   BS_ACCOUNTS),
            ("is",   IS_ACCOUNTS),
            ("cf",   CF_ACCOUNTS),
            ("note", NOTE_ACCOUNTS),
        ]
        for prefix, mapping in section_maps:
            for code, aliases in mapping.items():
                self._aliases_by_code[code] = aliases
                for alias in aliases:
                    self._exact_by_prefix[prefix][alias] = code
                    norm = normalize_account_name(alias)
                    if norm:
                        self._normalized_by_prefix[prefix][norm] = code

        # 하위 호환 병합 인덱스 (섹션 정보 없을 때 사용 — CF > IS > BS 순 override)
        all_maps = [BS_ACCOUNTS, IS_ACCOUNTS, CF_ACCOUNTS, NOTE_ACCOUNTS]
        for mapping in all_maps:
            for code, aliases in mapping.items():
                for alias in aliases:
                    self._exact[alias] = code
                    norm = normalize_account_name(alias)
                    if norm:
                        self._normalized[norm] = code

        # Precomputed (alias, normalized_alias) pairs for _fuzzy_match().
        # _fuzzy_match() used to call normalize_account_name() over the WHOLE alias
        # dictionary on every map() call: 1,011,495 calls / 15.2M re.sub for just 4,065
        # fuzzy matches -- 40% of Gate B audit wall time (profiled 2026-08-17, see
        # docs/plans/gateb_audit_performance_design_2026-08-17.md B1).
        # normalize_account_name() is pure and the alias set is immutable after
        # _build_index(), so this is a semantics-preserving memoization.
        # Order matters: _fuzzy_match() breaks ties with a strict `>` comparison, so the
        # first match wins. Build from _aliases_by_code (not the raw section maps) to
        # inherit its exact final content AND iteration order. Aliases whose normalized
        # form is empty are dropped here -- _fuzzy_match() skipped them anyway.
        self._aliases_norm_by_code: dict[str, list[tuple[str, str]]] = {}
        for code, aliases in self._aliases_by_code.items():
            pairs = []
            for alias in aliases:
                alias_norm = normalize_account_name(alias)
                if alias_norm:
                    pairs.append((alias, alias_norm))
            self._aliases_norm_by_code[code] = pairs

    # ── 3단계 매핑 ────────────────────────────────────────────────────

    def map(self, raw_account_name: str, fs_section: Optional[str] = None) -> MappingResult:
        """
        계정과목명을 표준 코드로 변환한다.

        Args:
            raw_account_name: DART XML/PDF에서 추출한 원문 계정과목명
            fs_section: 재무제표 섹션 힌트 ("bs", "is", "cf", "note").
                        제공 시 해당 섹션의 account_map을 우선 탐색해
                        같은 계정명이 여러 섹션에 있을 때의 혼용을 방지한다.
                        예: "감가상각비" → CF 섹션이면 cf.depreciation 반환

        Returns:
            MappingResult (account_code, confidence, stage)
        """
        if not raw_account_name or not raw_account_name.strip():
            return MappingResult("unknown.empty", 0.0, "unknown")

        raw = raw_account_name.strip()
        normalized = normalize_account_name(raw)

        # ── 섹션 우선 탐색 (fs_section 제공 시) ────────────────────────
        if fs_section and fs_section in self._exact_by_prefix:
            sec_exact = self._exact_by_prefix[fs_section]
            sec_norm  = self._normalized_by_prefix[fs_section]

            if raw in sec_exact:
                return MappingResult(sec_exact[raw], 1.0, "exact", raw)
            if normalized in sec_norm:
                return MappingResult(sec_norm[normalized], 1.0, "normalized", normalized)

        # ── Stage 1: 정확 일치 (전체 merged) ─────────────────────────
        if raw in self._exact:
            code = self._exact[raw]
            # fs_section 제공 시 반환 코드가 해당 섹션인지 확인
            # 다른 섹션 코드면 Stage 2로 넘어가지 않고 unknown 처리
            # (예: 'is.other_income'이 'bs' 섹션에서 반환되는 것 방지)
            if not fs_section or code.startswith(f"{fs_section}."):
                return MappingResult(code, 1.0, "exact", raw)

        # ── Stage 2: 정규화 후 일치 ───────────────────────────────────
        if normalized in self._normalized:
            code = self._normalized[normalized]
            if not fs_section or code.startswith(f"{fs_section}."):
                return MappingResult(code, 1.0, "normalized", normalized)

        # ── 퍼지 차단: 합산성 라벨(현금+예적금 등)은 퍼지로 bs.cash 오매핑 방지 → 무매핑 ──
        if normalized in _FUZZY_BLOCK:
            return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")

        # ── 세전이익(EBT) 가드: '차감전'(법인세비용/법인세 차감 전) = 세전이익이지 법인세비용(tax)이
        # 아니다. 라벨에 '법인세비용' 부분문자열이 있어 퍼지가 is.tax_expense 로 오매핑하던 변형
        # ('법인세비용차감전이익(손실)' 등 exact 미등록 케이스)을 차단해 is.ebt 로 귀속한다.
        # IS(또는 섹션 미지정)에서만 발동; CF 의 indirect-method 시작라인은 자체 처리(미발동).
        # 중단영업 차감전(=중단영업 세전손익)은 총 EBT 가 아니므로 무매핑(raw 보존, tax/ebt 비오염).
        if "차감전" in normalized and fs_section in (None, "is"):
            if "중단" in normalized:
                return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")
            return MappingResult("is.ebt", 0.95, "guard", raw)

        # ── 포괄손익 귀속(배분) 가드: '포괄손익, 지배기업소유주귀속지분'·'총포괄손익,비지배지분' 은
        # 총포괄손익의 지배/비지배 배분이지 **당기순이익 귀속**(controlling/noncontrolling NI)이 아니다.
        # 라벨에 '지배'가 있어 퍼지가 controlling_ni 로 오매핑 → net_income 합산(controlling+noncontrolling)
        # 을 오염시켰다(OCI≠0 일 때 총NI 과 불일치). 무매핑(raw 보존)으로 차단. 'IS' 한정.
        #
        # ★2026-08-25(NH투자증권 Gate B fail_b 근본원인 조사): 원래 이 가드는 '포괄손익'
        # (붙임표기)만 검사했는데, 상당수 필터社(증권사뿐 아니라 일반 상장사도, 254개사 실측)가
        # '포괄이익'/'포괄손실'로 **쪼개서** 표기한다('지배주주지분포괄이익'·'비지배지분포괄손실'
        # 등) — 이 변형은 가드를 못 넘어 fuzzy 로 controlling_ni/noncontrolling_ni 에
        # 오매핑됐다. 전수검사(283,030개 원문 XML, SD카드 미러 `/Volumes/dart_data/raw_report`,
        # 실 추출게이트와 동일하게 "라벨+숫자값 모두 있는 행"만 5,242건 확보, 오류 0) 결과:
        # 오탐 3,273건(is.controlling_ni 768 + is.noncontrolling_ni 2,505, 254개사/2,778
        # filing) 전부 원래 '포괄' 개념(순이익 아님) — '순이익'/'당기순'이 함께 들어간
        # 하이브리드 라벨은 **0건**(과차단 위험 없음, 스크립트 로직은
        # `gateb-nh-investment-controlling-ni-comprehensive-income-contamination-2026-08-25`
        # 메모리에 보존). NH투자증권(00120182) 실측: 이 가드가 넓어지면 Track B 일반매퍼가
        # controlling_ni/noncontrolling_ni 를 (틀린 값으로) 선점하지 않게 되어
        # `_with_ni_attribution_text_fallback()`의 스킵 게이트가 오발동하지 않고
        # `_ni_attribution_text_candidates()`(정답을 정확히 찾는 스코프제한 폴백)가 정상
        # 호출된다 — 정답 db_won=215,070백만 정확 복원 확인.
        if (("포괄손익" in normalized or "포괄이익" in normalized or "포괄손실" in normalized)
                and "지배" in normalized and fs_section in (None, "is")):
            return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")

        # ── 맨몸(bare) 지배지분 라벨 가드(2026-08-22, P1C 잔여회귀 조사 중 발견): '지배기업
        # 소유주지분'·'지배기업의 소유주'류처럼 "순이익/당기순/손실/귀속" 한정어가 전혀 없는
        # bare 라벨은 같은 IS 표 안에서 **당기순이익 귀속**(정답, is.controlling_ni)과
        # **총포괄손익 귀속**(오답)이 똑같은 bare 문구를 나란히 쓰는 문서(네오위즈 00628860 등,
        # 15개 기간 실측)에서 위 포괄손익 가드로도 못 막는다 — 그 문서엔 라벨 자체에 '포괄'이
        # 없기 때문. account_maps/is_accounts.py 가 이 bare 변형들을 alias 로 등록 안 해도
        # 퍼지의 '포함 관계' 매칭이 그 bare 문자열을 "…당기순이익"이 붙은 qualified alias 의
        # **부분문자열**로 보고 그리로 끌어당긴다(실측: alias 제거 후에도 fuzzy 0.9675 유지) —
        # 그래서 alias 리스트 정리만으론 못 막고 여기서 직접 차단해야 한다. 무매핑(raw 보존)
        # 으로 두면 `fin2/layer3/combine.py::_ni_attribution_structural_candidates()` /
        # `fin2/audit/face_audit.py::_ni_attribution_text_candidates()`(둘 다 section_path/
        # 앵커-스캔 기반, 라벨 무관) 가 안전하게 대신 분류한다. 'IS' 한정(BS 는 자본 개념이라
        # bs_accounts.py 가 이미 별도로 이 bare 형을 안 씀).
        if (fs_section in (None, "is") and "지배" in normalized
                and (normalized.endswith("지분") or normalized.endswith("소유주"))
                and not any(k in normalized for k in ("순이익", "순손실", "당기순", "손실", "귀속"))):
            return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")

        # ── 지배/비지배 귀속 중단영업 성분 가드(2026-08-23, fy≥2024 잔여회귀 조사 중 발견 —
        # 케이엔더블유 00606664): '지배주주지분순이익(중단)'처럼 귀속(지배/비지배) 라벨에
        # '중단'(중단영업/중단사업) 한정어가 붙으면 그건 계속+중단 합산 헤드라인 총계가 아니라
        # 중단영업 성분만의 부분값이다(이 회사는 중단영업분=0, 실제 총 controlling_ni는 별도
        # 라인 '지배기업지분'에 있음). 그런데도 '순이익' 키워드가 있어 위 bare 지배지분 가드는
        # 이 라벨을 그대로 통과시키고, 퍼지가 헤드라인 alias('지배주주순이익')와 근접(0.90+)
        # 하다고 보고 is.controlling_ni 로 오매핑한다. 평소엔 다른 진짜 후보와 충돌(conflicts)
        # 로 남아 _resolve_ni_attribution 의 identity 로 안전하게 걸러지는데, 위 bare 가드가
        # 그 진짜 후보들을 전부 무매핑시킨 뒤로는 이 부분값이 **유일한 후보**가 되어 conflict를
        # 아예 안 거치고(len==1) 곧장 확정돼버린다(단독후보 자동확정, 결측>오염 원칙 위반).
        # IS 한정, 지배/비지배 귀속 형태(끝이 지분/소유주 이거나 '귀속' 포함)로 범위 좁힘 —
        # 헤드라인 is.net_income/is.operating_income 의 '중단영업' 처리는 아래 기존 가드가 이미 담당.
        if (fs_section in (None, "is") and "지배" in normalized and "중단" in normalized
                and ("지분" in normalized or "소유주" in normalized or "귀속" in normalized)):
            return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")

        # ── 지분법 지분 가드: '지분법적용대상…당기순손익에대한지분'(피투자기업 순손익 지분) 은
        # 지분법손익(equity_method_income)이지 당기순이익(net_income)이 아니다. '당기순손익' 부분문자열로
        # is.net_income 오매핑 → fill 우회(net_income 오염)되던 것 차단(is.equity_method_income 로 귀속).
        if "지분법" in normalized and ("당기순손익" in normalized or "당기순이익" in normalized) \
                and fs_section in (None, "is"):
            return MappingResult("is.equity_method_income", 0.9, "guard", raw)

        # ── 영업이익 오매핑 가드(C5 크로스소스로 발견, 2026-07-06): '계속영업이익(손실)'·
        # '중단영업이익(손실)'(세후 계속/중단영업 손익 소계, 순이익에 인접한 개념)과 '영업외손익'
        # 계열(영업외수익-비용 순액)은 영업이익(is.operating_income)이 아니다. alias '영업이익
        # (손실)'/'영업손익' 과의 부분포함(len_ratio 0.8)·근접 Jaro-Winkler 유사도로 Stage 3 가
        # 잘못 흡수(신뢰도 0.9~0.97) → build.py max-abs 선택에서 이 큰 값이 진짜 영업이익을
        # 가려 부호까지 뒤집힘(금호타이어 2022 등, 크로스소스 검증 65건 중 다수). '주당'(EPS)
        # 파생 라인도 같은 substring 이라 동반 차단(원단위 canonical 에 EPS 오염 방지).
        # '차감전'(세전) 계속영업 변형은 위 EBT 가드가 이미 처리했으므로 여기 도달 안 함.
        if fs_section in (None, "is"):
            # ── 주당(EPS) 가드: '기본주당기순손익'·'희석주당기순손익' 등 주당(원/주) 파생 라인은
            # 퍼지가 '당기순손익' 과 0.94 유사도로 is.net_income 오매핑 → 원단위 net_income 이
            # ~0(주당 수십 원)으로 오염(이월드 2013H1 net 0억, controlling_ni 비율 폭증). '주당'
            # 포함 라인은 원단위 손익 canonical 에서 배제(원래 line 188 주석이 의도했으나 미구현분).
            if "주당" in normalized:
                return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")
            if "계속영업" in normalized or "중단영업" in normalized:
                return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")
            if "영업외" in normalized and ("이익" in normalized or "손익" in normalized):
                return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")

        # ── Stage 3: 퍼지 매핑 ────────────────────────────────────────
        # fs_section 제공 시 섹션-한정 퍼지 먼저 시도, 없으면 전체 퍼지 (단, 섹션 접두사가
        # 불일치하는 코드는 최종 후보에서 제외 — 예: BS 컨텍스트에서 IS 코드 반환 방지)
        fuzzy_result = self._fuzzy_match(raw, normalized, fs_section=fs_section)
        if fuzzy_result:
            return fuzzy_result

        # ── 실패: unknown 코드 반환 ────────────────────────────────────
        safe_name = re.sub(r'[^\w가-힣]', '_', normalized)[:80]
        return MappingResult(f"unknown.{safe_name}", 0.0, "unknown")

    def _fuzzy_match(
        self,
        raw: str,
        normalized: str,
        fs_section: Optional[str] = None,
    ) -> Optional[MappingResult]:
        """
        퍼지 매핑: 포함 관계 우선, 그 다음 Jaro-Winkler 유사도.
        jellyfish가 없으면 포함 관계만 시도.

        fs_section이 제공되면 **동일 섹션의 코드만** 후보로 사용한다.
        예: fs_section="bs" → bs.* 코드만 퍼지 매칭 (IS/CF 코드로 오매핑 방지).
        섹션 내 후보 없으면 None 반환 (크로스-섹션 폴백 없음).
        """
        best_code: Optional[str] = None
        best_score: float = 0.0
        best_alias: Optional[str] = None

        # _aliases_norm_by_code = precomputed (alias, alias_norm) pairs — same content and
        # order as _aliases_by_code, minus aliases that normalize to "" (which this loop
        # used to skip). See _build_index().
        for code, alias_pairs in self._aliases_norm_by_code.items():
            # fs_section 제공 시 동일 섹션 코드만 허용
            if fs_section and not code.startswith(f"{fs_section}."):
                continue

            for alias, alias_norm in alias_pairs:
                # 포함 관계: alias가 normalized 안에 있으면 높은 점수
                if alias_norm in normalized or normalized in alias_norm:
                    # 더 긴 쪽 / 짧은 쪽 비율로 점수 조절
                    len_ratio = min(len(alias_norm), len(normalized)) / max(len(alias_norm), len(normalized), 1)
                    # 짧은 단어(3자 이하)가 긴 단어의 접미사/접두사인 경우 오탐 방지
                    # 예: "합계"(2자) in "급여합계"(4자) → len_ratio=0.5 → skip
                    # 단, 완전 일치(len_ratio=1.0)는 항상 허용
                    if len_ratio < 0.65 and min(len(alias_norm), len(normalized)) <= 4:
                        # 너무 짧은 단어가 부분 매칭되는 경우 → Jaro-Winkler로만 처리
                        pass
                    else:
                        score = 0.90 + len_ratio * 0.09  # 0.90 ~ 0.99
                        if score > best_score:
                            best_score = score
                            best_code = code
                            best_alias = alias
                    continue

                # Jaro-Winkler 유사도
                if _HAS_JELLYFISH and len(alias_norm) >= 3 and len(normalized) >= 3:
                    score = jellyfish.jaro_winkler_similarity(normalized, alias_norm)
                    if score >= self.fuzzy_threshold and score > best_score:
                        best_score = score
                        best_code = code
                        best_alias = alias

        if best_code and best_score >= self.fuzzy_threshold:
            return MappingResult(best_code, best_score, "fuzzy", best_alias)

        return None

    def get_all_codes(self) -> list[str]:
        """등록된 모든 표준 계정 코드 반환"""
        return list(self._aliases_by_code.keys())

    def get_aliases(self, account_code: str) -> list[str]:
        """특정 코드의 alias 목록 반환"""
        return self._aliases_by_code.get(account_code, [])


# ── 싱글턴 (모듈 레벨 캐싱) ──────────────────────────────────────────
_mapper_instance: Optional[AccountMapper] = None


def get_mapper() -> AccountMapper:
    """싱글턴 AccountMapper 반환 (최초 1회만 인덱스 빌드)"""
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = AccountMapper()
    return _mapper_instance
