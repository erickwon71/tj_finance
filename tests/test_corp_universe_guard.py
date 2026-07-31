"""collector 상장 유니버스 소스 신뢰도 가드 회귀 테스트 (V6a/V6c).

고정하는 사실:
  ① 한 시장의 목록 조회가 실패하면 그 시장 종목이 통째로 후보에서 빠진다. 예전 코드는
     이를 경고만 하고 진행해 **그 시장 전체를 is_active=False** 로 내렸다(KOSPI 809개).
     파일 삭제가 연결됐다면 원문이 한 번에 사라진다.
  ② 수정 후에는 **KRX OpenAPI + FDR 상호보완**이라 한쪽이 죽어도 그 시장이 살아남고,
     **둘 다 죽은 시장**이 있을 때만 `may_deactivate=False` 로 비활성 처리를 건너뛴다.
     upsert(신규 상장 반영)는 어느 경우에도 계속한다.
  ③ HTTP 200 + 0건(KRX 의 함정)과 빈 DataFrame(FDR)은 **실패로 센다.**

네트워크를 타지 않도록 fdr.StockListing 과 krx_client.fetch_all 을 가짜로 바꾼다.
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import corp_collector as cc  # noqa: E402
from tests._util import run_tests  # noqa: E402


class _FakeDF:
    """FinanceDataReader.StockListing 반환값의 최소 대역 — Code 컬럼만 흉내낸다."""

    def __init__(self, codes: list[str]):
        self._codes = codes
        self.columns = ["Code"]
        self.empty = not codes

    def __len__(self):
        return len(self._codes)

    def __getitem__(self, key):
        assert key == "Code"
        return _FakeSeries(self._codes)


class _FakeSeries:
    def __init__(self, codes):
        self._codes = codes

    def astype(self, _):
        return self

    @property
    def str(self):
        return self

    def strip(self):
        return self._codes

    def __iter__(self):
        return iter(self._codes)


@contextmanager
def fake_fdr(kospi: list[str] | None, kosdaq: list[str] | None):
    """None = 조회 예외. [] = 빈 결과(역시 실패로 간주돼야 함)."""
    mod = types.ModuleType("FinanceDataReader")

    def StockListing(market):  # noqa: N802 (외부 API 이름)
        data = kospi if market == "KOSPI" else kosdaq
        if data is None:
            raise RuntimeError(f"{market} 조회 실패(주입)")
        return _FakeDF(data)

    mod.StockListing = StockListing
    saved = sys.modules.get("FinanceDataReader")
    sys.modules["FinanceDataReader"] = mod
    try:
        yield
    finally:
        if saved is None:
            sys.modules.pop("FinanceDataReader", None)
        else:
            sys.modules["FinanceDataReader"] = saved


@contextmanager
def fake_krx(kospi: list[str] | None, kosdaq: list[str] | None):
    """krx_client.fetch_all 대역. None = 실패(인증/빈목록). []도 실패로 간주됨."""
    from collector import krx_client as kc

    def fetch_all(bas_dd=None):
        uni, results = {}, {}
        for market, codes in (("KOSPI", kospi), ("KOSDAQ", kosdaq)):
            if codes:
                results[market] = kc.MarketListing(
                    market, bas_dd="20260730",
                    rows=[{"ISU_SRT_CD": c, "MKT_TP_NM": market,
                           "KIND_STKCERT_TP_NM": "보통주", "SECUGRP_NM": "주권"}
                          for c in codes])
                uni.update({c: market for c in codes})
            else:
                results[market] = kc.MarketListing(
                    market, error="서비스 미승인 또는 활용기간 만료(주입)")
        return uni, results

    saved = kc.fetch_all
    kc.fetch_all = fetch_all
    try:
        yield
    finally:
        kc.fetch_all = saved


def _may_deactivate(status: dict) -> bool:
    return not [m for m, st in status.items() if st["used"] is None]


# ── 정상 ────────────────────────────────────────────────────────────

def test_both_sources_ok_prefers_krx():
    """둘 다 살아 있으면 KRX 를 쓴다(우선주·펀드를 소스에서 걸러주므로)."""
    with fake_krx(["005930", "000660"], ["035720"]), fake_fdr(["005930", "000660", "000661"],
                                                              ["035720"]):
        universe, status = cc._get_krx_universe()
    assert universe is not None
    assert status["KOSPI"]["used"] == "krx", status
    assert status["KOSDAQ"]["used"] == "krx"
    assert "000661" not in universe, "KRX 를 썼다면 FDR 의 우선주가 섞이면 안 된다"


# ── 상호보완 ────────────────────────────────────────────────────────

def test_krx_auth_failure_falls_back_to_fdr():
    """KRX 활용기간 만료(401) → 그 시장은 FDR 로 살린다."""
    with fake_krx(None, None), fake_fdr(["005930"], ["035720"]):
        universe, status = cc._get_krx_universe()
    assert universe is not None and len(universe) == 2
    assert status["KOSPI"]["used"] == "fdr", status
    assert _may_deactivate(status) is True, "폴백이 성공했으면 비활성 처리는 허용된다"


def test_fdr_failure_falls_back_to_krx():
    with fake_krx(["005930"], ["035720"]), fake_fdr(None, None):
        universe, status = cc._get_krx_universe()
    assert universe is not None and len(universe) == 2
    assert status["KOSPI"]["used"] == "krx"
    assert _may_deactivate(status) is True


def test_one_market_survives_via_other_source():
    """KOSPI 는 KRX 만, KOSDAQ 은 FDR 만 살아 있어도 양쪽 다 신뢰 가능."""
    with fake_krx(["005930"], None), fake_fdr(None, ["035720"]):
        universe, status = cc._get_krx_universe()
    assert status["KOSPI"]["used"] == "krx"
    assert status["KOSDAQ"]["used"] == "fdr"
    assert _may_deactivate(status) is True
    assert len(universe) == 2


# ── V6a: 한 시장이 두 소스 모두 실패 ────────────────────────────────

def test_market_dead_in_both_sources_blocks_deactivation():
    """핵심 회귀 — KOSPI 가 양쪽 다 죽으면 비활성 처리를 막아야 한다."""
    with fake_krx(None, ["035720"]), fake_fdr(None, ["035720", "247540"]):
        universe, status = cc._get_krx_universe()
    assert universe is not None, "KOSDAQ 은 살았으므로 universe 는 있다"
    assert status["KOSPI"]["used"] is None, "KOSPI 실패가 삼켜졌다 — 809개가 비활성될 수 있다"
    assert _may_deactivate(status) is False, "두 소스 모두 실패인데 비활성 처리가 허용됐다"


def test_empty_result_counts_as_failure():
    """빈 결과(KRX 의 HTTP 200+0건, FDR 의 df.empty)를 성공으로 세면 같은 사고가 난다."""
    with fake_krx(["005930"], []), fake_fdr(["005930"], []):
        _, status = cc._get_krx_universe()
    assert status["KOSDAQ"]["used"] is None, "빈 결과가 성공으로 처리됐다"
    assert _may_deactivate(status) is False


# ── V6c: DART 단독 모드 ─────────────────────────────────────────────

def test_all_sources_fail_returns_none():
    with fake_krx(None, None), fake_fdr(None, None):
        universe, status = cc._get_krx_universe()
    assert universe is None, "전 소스 실패면 DART 단독 모드(None)여야 한다"
    assert all(st["used"] is None for st in status.values())


def test_dart_only_mode_blocks_deactivation():
    with fake_krx(None, None), fake_fdr(None, None):
        universe, status = cc._get_krx_universe()
    krx_mode = universe is not None
    assert (krx_mode and _may_deactivate(status)) is False


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
