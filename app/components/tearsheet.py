"""
기업 요약 tearsheet — matplotlib 로 A4 한 페이지 PDF 생성(D4).

CSV 가 raw 데이터 export 라면, tearsheet 는 **한 장짜리 시각 요약**(밸류에이션 스냅샷 +
재무/수익성 표 + 매출·이익 / ROE·마진 추이 차트)이다. 외부 서비스·신규 의존성 없이 이미
설치된 matplotlib 만으로 PDF bytes 를 만들어 st.download_button 으로 내려준다.

값 규약: series/mv 는 원시값(금액=원, 비율=소수). 표시에서 억원(÷1e8)·%(×100) 변환.
"""
from __future__ import annotations

import io
from datetime import date

import matplotlib
matplotlib.use("Agg")  # 헤드리스/스트림릿 안전
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from analyzer.ratio_engine import compute_ratios

_EOK = 100_000_000
# 한글 렌더 폰트(맥 우선순위) — 없으면 기본 폰트(한글 깨질 수 있음).
_FONT_PREF = ["AppleGothic", "Apple SD Gothic Neo", "Nanum Gothic", "NanumGothic",
              "Malgun Gothic", "Noto Sans CJK KR"]


def _pick_font() -> str | None:
    names = {f.name for f in fm.fontManager.ttflist}
    for cand in _FONT_PREF:
        if cand in names:
            return cand
    return None


def _eok(v) -> float | None:
    return (v / _EOK) if v is not None else None


def _fmt_eok(v) -> str:
    e = _eok(v)
    return f"{e:,.0f}" if e is not None else "—"


def _fmt_pct(v) -> str:
    return f"{v * 100:.1f}%" if v is not None else "—"


def _fmt_x(v) -> str:
    return f"{v:.2f}x" if v is not None else "—"


def _fmt_won(v) -> str:
    return f"{v:,.0f}원" if v is not None else "—"


def build_tearsheet_pdf(meta: dict, series: list[dict], mv: dict | None,
                        used_stmt: str) -> bytes:
    """meta(resolve_corp) + 연간 series(최신→과거) + mv(멀티플) → A4 PDF bytes."""
    font = _pick_font()
    if font:
        plt.rcParams["font.family"] = font
    plt.rcParams["axes.unicode_minus"] = False  # 한글폰트 음수기호 깨짐 방지

    # 과거→최신 정렬(차트/표 시간축)
    chrono = sorted(series, key=lambda r: r.get("fiscal_year") or 0)
    recent = chrono[-8:]
    years = [str(r.get("fiscal_year")) for r in recent]

    fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
    gs = fig.add_gridspec(nrows=6, ncols=2, height_ratios=[0.9, 0.7, 1.5, 1.5, 1.9, 0.4],
                          hspace=0.55, wspace=0.18,
                          left=0.06, right=0.94, top=0.96, bottom=0.04)

    # ── 헤더 ──────────────────────────────────────────────
    ax_h = fig.add_subplot(gs[0, :]); ax_h.axis("off")
    name = meta.get("corp_name", "")
    code = meta.get("stock_code") or meta.get("corp_code", "")
    market = meta.get("market") or ""
    basis_ko = "연결" if used_stmt == "consolidated" else "별도"
    latest_fy = recent[-1].get("fiscal_year") if recent else "—"
    ax_h.text(0, 0.75, f"{name}", fontsize=20, fontweight="bold", va="top")
    ax_h.text(0, 0.30, f"{code} · {market} · 재무기준 {basis_ko} · 최신 FY {latest_fy}",
              fontsize=10, color="#555", va="top")
    ax_h.text(1, 0.75, f"작성일 {date.today().isoformat()}", fontsize=8,
              color="#888", va="top", ha="right")
    ax_h.axhline(0.05, color="#333", lw=1.2)

    # ── 밸류에이션 스냅샷 ─────────────────────────────────
    ax_v = fig.add_subplot(gs[1, :]); ax_v.axis("off")
    ax_v.text(0, 1.0, "밸류에이션 (최신 FY)", fontsize=11, fontweight="bold", va="top")
    mv = mv or {}
    val_items = [
        ("시가총액", _fmt_eok(mv.get("market_cap")) + ("억" if mv.get("market_cap") else "")),
        ("PER", _fmt_x(mv.get("per"))), ("PBR", _fmt_x(mv.get("pbr"))),
        ("PSR", _fmt_x(mv.get("psr"))), ("EV/EBITDA", _fmt_x(mv.get("ev_ebitda"))),
        ("EPS", _fmt_won(mv.get("eps"))), ("BPS", _fmt_won(mv.get("bps"))),
        ("배당수익률", _fmt_pct(mv.get("dividend_yield"))),
    ]
    n = len(val_items)
    for i, (k, v) in enumerate(val_items):
        x = i / n
        ax_v.text(x, 0.55, k, fontsize=8, color="#666", va="top")
        ax_v.text(x, 0.20, v, fontsize=10, fontweight="bold", va="top")

    # ── 재무 요약 표 ──────────────────────────────────────
    ax_f = fig.add_subplot(gs[2, :]); ax_f.axis("off")
    ax_f.text(0, 1.06, "재무 요약 (억원)", fontsize=11, fontweight="bold", va="top",
              transform=ax_f.transAxes)
    fin_rows = [("매출액", "revenue"), ("영업이익", "operating_income"),
                ("순이익", "net_income"), ("자산총계", "total_assets"),
                ("자본총계", "total_equity")]
    fin_data = [[_fmt_eok(r.get(key)) for r in recent] for _, key in fin_rows]
    _draw_table(ax_f, [lbl for lbl, _ in fin_rows], years, fin_data)

    # ── 수익성·안정성 표 ─────────────────────────────────
    ax_r = fig.add_subplot(gs[3, :]); ax_r.axis("off")
    ax_r.text(0, 1.06, "수익성 · 안정성", fontsize=11, fontweight="bold", va="top",
              transform=ax_r.transAxes)
    ratios = _ratios_by_year(recent)
    ratio_rows = [("ROE", "roe"), ("영업이익률", "op_margin"), ("순이익률", "net_margin"),
                  ("부채비율", "debt_ratio")]
    ratio_data = [[_fmt_pct(ratios[i].get(key)) for i in range(len(recent))]
                  for _, key in ratio_rows]
    _draw_table(ax_r, [lbl for lbl, _ in ratio_rows], years, ratio_data)

    # ── 차트 1: 매출·영업이익 추이 ────────────────────────
    ax_c1 = fig.add_subplot(gs[4, 0])
    rev = [_eok(r.get("revenue")) for r in recent]
    op = [_eok(r.get("operating_income")) for r in recent]
    ax_c1.plot(years, rev, marker="o", color="#1f77b4", label="매출액", lw=1.6)
    ax_c1.plot(years, op, marker="s", color="#d62728", label="영업이익", lw=1.6)
    ax_c1.set_title("매출·영업이익 (억원)", fontsize=9)
    ax_c1.legend(fontsize=7, loc="upper left"); ax_c1.grid(alpha=0.25)
    ax_c1.tick_params(labelsize=7)

    # ── 차트 2: ROE·영업이익률 추이 ───────────────────────
    ax_c2 = fig.add_subplot(gs[4, 1])
    roe = [(ratios[i].get("roe") or 0) * 100 if ratios[i].get("roe") is not None else None
           for i in range(len(recent))]
    opm = [(ratios[i].get("op_margin") or 0) * 100 if ratios[i].get("op_margin") is not None else None
           for i in range(len(recent))]
    ax_c2.plot(years, roe, marker="o", color="#2ca02c", label="ROE", lw=1.6)
    ax_c2.plot(years, opm, marker="s", color="#ff7f0e", label="영업이익률", lw=1.6)
    ax_c2.set_title("ROE·영업이익률 (%)", fontsize=9)
    ax_c2.legend(fontsize=7, loc="upper left"); ax_c2.grid(alpha=0.25)
    ax_c2.tick_params(labelsize=7)

    # ── 푸터 ──────────────────────────────────────────────
    ax_ft = fig.add_subplot(gs[5, :]); ax_ft.axis("off")
    ax_ft.text(0, 0.5, "출처: DART 정기보고서 표준화 DB(TJ Finance). 금액=억원, 비율=%. "
               "값은 공시 원문과 일치(Gate B 검증). 투자판단의 근거로 삼기 전 원문 확인 권장.",
               fontsize=6.5, color="#888", va="center", wrap=True)

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(fig)
    plt.close(fig)
    return buf.getvalue()


def _ratios_by_year(recent: list[dict]) -> list[dict]:
    """recent(과거→최신)의 각 연도별 비율 dict. 전기=직전(더 과거) 행."""
    out = []
    for i, r in enumerate(recent):
        prev = recent[i - 1] if i > 0 else None
        fr = compute_ratios(r, prev)
        out.append({k: getattr(fr, k, None)
                    for k in ("roe", "op_margin", "net_margin", "debt_ratio")})
    return out


def _draw_table(ax, row_labels: list[str], col_labels: list[str],
                cell_data: list[list[str]]) -> None:
    """간단 표를 axes 에 그린다. 행 라벨은 좌측 클리핑을 피해 첫 컬럼으로 넣는다."""
    header = [""] + col_labels
    body = [[row_labels[i]] + cell_data[i] for i in range(len(row_labels))]
    table = ax.table(cellText=body, colLabels=header, cellLoc="right", loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.4)

    ncols = len(header)
    label_w, data_w = 0.20, 0.80 / (ncols - 1)  # 라벨 컬럼을 넓게
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#ddd")
        cell.set_width(label_w if col == 0 else data_w)
        if row == 0:  # 헤더행
            cell.set_facecolor("#f0f3f7")
            cell.set_text_props(fontweight="bold")
        if col == 0:  # 라벨 컬럼(좌측정렬·강조)
            cell.set_text_props(ha="left", fontweight="bold")
            cell.set_facecolor("#f7f9fb")
