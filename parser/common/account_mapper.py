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

        for code, aliases in self._aliases_by_code.items():
            # fs_section 제공 시 동일 섹션 코드만 허용
            if fs_section and not code.startswith(f"{fs_section}."):
                continue

            for alias in aliases:
                alias_norm = normalize_account_name(alias)
                if not alias_norm:
                    continue

                # 포함 관계: alias가 normalized 안에 있으면 높은 점수
                if alias_norm in normalized or normalized in alias_norm:
                    # 더 긴 쪽 / 짧은 쪽 비율로 점수 조절
                    overlap_ratio = min(len(alias_norm), len(normalized)) / max(len(alias_norm), len(normalized))
                    score = 0.90 + overlap_ratio * 0.09  # 0.90 ~ 0.99
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
