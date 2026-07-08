"""
Tier-1 automated sweep — 기업 시각화 페이지 x {연간,분기} x {연결,별도} (docs/qa §A).

For each (corp_code, stock_code) and each of the 4 combos:
  - loads /company, selects the company via sidebar search,
  - sets the 연결/별도 and 연간/분기 radios,
  - on the 재무제표 tab: drags the period-range slider to the full available
    span, downloads the raw-KRW CSV (the app's own CV-3 export button) and
    parses it — this sidesteps the fact that st.dataframe renders on a canvas
    (glide-data-grid) and is not scrapable as DOM text,
  - cross-checks revenue/operating_income from the CSV against the DB
    (`standard_financials` for annual, `calendar_financials` for quarter —
    the same views/tables app/data/series.py itself queries) for:
      DS-2 (value diff) and DS-3 (mid-series gap, app-bug vs data-gap split),
  - visits the 지표 tab and takes a presence/no-crash reading,
  - checks DS-1 (python traceback / Streamlit exception box / blank page),
    DS-4 (연결/별도 substitution caption), DS-8 (header identity vs DB).

Resumable: skips (corp_code, combo) pairs already present in
docs/qa/results/sweep_all_companies.csv.

Usage:
  .venv_tj_finance/bin/python3 scripts/qa/sweep_company_pages.py --input docs/qa/results/sample_set.csv
  .venv_tj_finance/bin/python3 scripts/qa/sweep_company_pages.py --corp-codes 00126380,00164779
  .venv_tj_finance/bin/python3 scripts/qa/sweep_company_pages.py --random 20   # random extra batch

Sharding for parallel full-sweep runs (multiple concurrent OS processes):
  .venv_tj_finance/bin/python3 scripts/qa/sweep_company_pages.py \\
      --input docs/qa/results/shards/shard_1.csv --port 8502 --shard-tag shard1
  .venv_tj_finance/bin/python3 scripts/qa/sweep_company_pages.py \\
      --input docs/qa/results/shards/shard_2.csv --port 8503 --shard-tag shard2
  # ... one process per shard, each pointed at its OWN Streamlit instance (--port)
  # and its OWN output CSVs (--shard-tag) so concurrent writers never touch the
  # same file. Without --shard-tag, output goes to the original unsuffixed
  # filenames (docs/qa/results/sweep_all_companies.csv etc.) for backward
  # compatibility with the single-process pilot run.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402
from collector.db import get_session  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

RESULTS_DIR = os.path.join(ROOT, "docs", "qa", "results")
SHOTS_DIR = os.path.join(RESULTS_DIR, "shots")
SHARDS_DIR = os.path.join(RESULTS_DIR, "shards")

# These five are module-level so every helper function can see them without
# threading extra parameters through the whole call chain. main() overwrites
# them (via `global`) right after parsing --port/--shard-tag, BEFORE any
# Playwright/IO call happens, so every downstream function picks up the
# shard-specific values on first use. Defaults below preserve the original
# single-process pilot behavior (no --shard-tag => original unsuffixed
# filenames, port 8501) for backward compatibility.
BASE_URL = "http://localhost:8501"
SWEEP_CSV = os.path.join(RESULTS_DIR, "sweep_all_companies.csv")
GAPS_CSV = os.path.join(RESULTS_DIR, "mid_gaps.csv")
DIFFS_CSV = os.path.join(RESULTS_DIR, "value_diffs.csv")
TIMING_CSV = os.path.join(RESULTS_DIR, "sweep_timing.csv")

SWEEP_HEADER = ["company", "corp_code", "stock_code", "market", "combo", "tab",
                "check_id", "result", "detail", "elapsed_sec", "timestamp"]
GAPS_HEADER = ["company", "corp_code", "combo", "metric", "period", "classification",
               "detail", "timestamp"]
DIFFS_HEADER = ["company", "corp_code", "combo", "period", "metric",
                "ui_csv_value", "db_value", "diff_pct", "timestamp"]

COMBOS = [
    ("annual", "consolidated", "연간", "연결"),
    ("annual", "separate", "연간", "별도"),
    ("quarter", "consolidated", "분기", "연결"),
    ("quarter", "separate", "분기", "별도"),
]

# CSV row label -> DB column name (only the two DS-2 metrics required by the brief)
METRIC_MAP = {"매출액": "revenue", "영업이익": "operating_income"}

TOL_REL = 0.005  # 0.5% relative tolerance (per direction doc)


# ───────────────────────── CSV/output helpers (resumability) ─────────────────

def _ensure_files():
    os.makedirs(SHOTS_DIR, exist_ok=True)
    for path, header in [(SWEEP_CSV, SWEEP_HEADER), (GAPS_CSV, GAPS_HEADER),
                         (DIFFS_CSV, DIFFS_HEADER)]:
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(header)
    if not os.path.exists(TIMING_CSV):
        with open(TIMING_CSV, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["corp_code", "combo", "phase", "seconds", "timestamp"])


def _done_combos() -> set:
    """(corp_code, combo) pairs that already have at least one sweep row."""
    done = set()
    if not os.path.exists(SWEEP_CSV):
        return done
    with open(SWEEP_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            done.add((row["corp_code"], row["combo"]))
    return done


def _append_rows(path, header, rows):
    if not rows:
        return
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow(r)


# ───────────────────────── DB helpers ─────────────────────────────────────

def db_annual_row(corp_code: str, statement_type: str, fiscal_year: int):
    sql = """
        SELECT revenue, operating_income FROM standard_financials
        WHERE corp_code=:c AND statement_type=:s AND fiscal_period='FY' AND fiscal_year=:y
        ORDER BY calculated_at DESC LIMIT 1
    """
    with get_session() as s:
        row = s.execute(text(sql), {"c": corp_code, "s": statement_type, "y": fiscal_year}).mappings().fetchone()
    return dict(row) if row else None


def db_quarter_row(corp_code: str, statement_type: str, calendar_year: int, calendar_period: str):
    sql = """
        SELECT revenue, operating_income FROM calendar_financials
        WHERE corp_code=:c AND statement_type=:s AND calendar_year=:y AND calendar_period=:p
        ORDER BY calculated_at DESC LIMIT 1
    """
    with get_session() as s:
        row = s.execute(text(sql), {"c": corp_code, "s": statement_type, "y": calendar_year, "p": calendar_period}).mappings().fetchone()
    return dict(row) if row else None


def db_annual_all_years(corp_code: str, statement_type: str) -> dict:
    """fiscal_year -> {revenue, operating_income} for the WHOLE history (mid-gap ground truth)."""
    sql = """
        SELECT fiscal_year, revenue, operating_income FROM standard_financials
        WHERE corp_code=:c AND statement_type=:s AND fiscal_period='FY'
        ORDER BY fiscal_year
    """
    with get_session() as s:
        rows = s.execute(text(sql), {"c": corp_code, "s": statement_type}).mappings().fetchall()
    out = {}
    for r in rows:
        out[r["fiscal_year"]] = out.get(r["fiscal_year"], {})
        # keep the row with any non-null value if duplicates (versions) exist
        cur = out[r["fiscal_year"]]
        if r["revenue"] is not None or "revenue" not in cur:
            cur["revenue"] = r["revenue"] if r["revenue"] is not None else cur.get("revenue")
        if r["operating_income"] is not None or "operating_income" not in cur:
            cur["operating_income"] = r["operating_income"] if r["operating_income"] is not None else cur.get("operating_income")
    return out


def db_quarter_all(corp_code: str, statement_type: str) -> dict:
    sql = """
        SELECT calendar_year, calendar_period, revenue, operating_income FROM calendar_financials
        WHERE corp_code=:c AND statement_type=:s AND calendar_period IN ('CQ1','CQ2','CQ3','CQ4')
        ORDER BY calendar_year, calendar_period
    """
    with get_session() as s:
        rows = s.execute(text(sql), {"c": corp_code, "s": statement_type}).mappings().fetchall()
    out = {}
    for r in rows:
        key = (r["calendar_year"], r["calendar_period"])
        out[key] = {"revenue": r["revenue"], "operating_income": r["operating_income"]}
    return out


# ───────────────────────── Playwright helpers ─────────────────────────────

def _page_not_found_dialog_present(page) -> bool:
    try:
        dialogs = page.evaluate(
            "() => Array.from(document.querySelectorAll('[role=\"dialog\"]'))"
            ".map(d => d.textContent.slice(0,40))"
        )
    except Exception:
        return False
    return any("Page not found" in d for d in dialogs)


def dismiss_cold_start_dialog(page):
    """First navigation to a deep-linked url_path shows a transient 'Page not
    found' modal that intercepts all clicks until the page is reloaded
    (observed defect-adjacent behavior — see report). Retry reload until the
    modal is gone (bounded, since it should clear within 1-2 reloads)."""
    page.goto(f"{BASE_URL}/company", wait_until="networkidle", timeout=30000)
    time.sleep(1.0)
    for _ in range(5):
        if not _page_not_found_dialog_present(page):
            break
        page.reload(wait_until="networkidle", timeout=30000)
        time.sleep(1.5)


def select_company(page, query: str) -> bool:
    """.fill() focuses the input itself (no separate .click() needed) — a
    prior .click() occasionally raced a leftover 'Press Enter to apply'
    instruction tooltip from an earlier unsubmitted keystroke and timed out
    on the actionability check."""
    inp = page.get_by_placeholder("예: 삼성전자 / 005930")
    inp.fill("")
    inp.fill(query)
    inp.press("Enter")
    time.sleep(1.5)
    body = page.inner_text("body")
    if "검색 결과 없음" in body:
        return False
    # multi-match: radio + 선택 button. NOTE the radio group's own label
    # ("결과") is rendered with label_visibility="collapsed" so it does NOT
    # appear in page.inner_text("body") even though the widget is present —
    # detect multi-match via the [선택] button + >1 sidebar radio option
    # instead of searching body text for the (invisible) group label.
    option_labels = page.locator('[data-testid="stSidebar"] [data-testid="stRadio"] label')
    select_btn = page.locator('button:has-text("선택")')
    if select_btn.count() > 0 and option_labels.count() > 1:
        try:
            option_labels.nth(1).evaluate("el => el.click()")  # nth(0) is the collapsed group label
            select_btn.first.evaluate("el => el.click()")
            time.sleep(1.2)
        except Exception:
            pass
    return True


def set_radio(page, group_options: list[str], value: str):
    """Click an st.radio option by its exact visible label text, scoped to
    stRadio widgets only (avoids matching unrelated buttons/captions that
    happen to contain the same substring, e.g. the CSV download button).

    IMPORTANT (found via investigation of a false CSV-value-diff flag on
    마키나락스): clicking a BaseWeb radio <label> — via either a real
    Playwright .click() or a JS .click() — sometimes has NO EFFECT even
    though elementFromPoint confirms the click lands on the exact right
    node, and even with multi-second waits. It is intermittent (observed a
    run where 2 consecutive clicks on the same option were silently
    dropped, then a 3rd identical click worked). Root cause not fully
    isolated (candidate: a BaseWeb/React re-render race specific to this
    custom radio widget), but the fix is the same regardless: verify the
    underlying <input>'s checked state actually changed after the click,
    and retry if not — never trust a single click for a radio toggle."""
    _click_radio_verified(page, value)


def _radio_checked(page, value: str) -> bool:
    """True if the <input> inside the label matching `value` is checked."""
    loc = page.locator('[data-testid="stRadio"] label', has_text=value).first
    if loc.count() == 0:
        return False
    inp = loc.locator("input")
    try:
        return inp.is_checked()
    except Exception:
        return False


def _click_radio_verified(page, value: str, attempts: int = 4) -> bool:
    """Click a radio option by visible label text and verify the underlying
    input actually became checked, retrying on silent no-ops (see set_radio
    docstring). Returns True once verified, False if all attempts failed
    (caller proceeds anyway but the sweep row should be treated with
    suspicion if downstream checks look inconsistent)."""
    loc = page.locator('[data-testid="stRadio"] label').filter(
        has=page.locator(f'text="{value}"'))
    if loc.count() == 0:
        loc = page.locator('[data-testid="stRadio"] label', has_text=value)
    for attempt in range(attempts):
        if _radio_checked(page, value):
            return True
        loc.first.click(force=True)
        time.sleep(1.0 + 0.5 * attempt)
    return _radio_checked(page, value)


TAB_LABELS = ["📑 재무제표", "📊 지표", "💰 밸류에이션", "🏆 대가지표", "📈 주가",
              "📊 주가·재무 결합", "🏭 생산·가동률", "🏢 섹터·피어", "👔 임원·지분"]


def click_tab(page, tab_label: str):
    """tab_label must be one of TAB_LABELS (includes the emoji prefix so it
    cannot collide with body text, e.g. '📑 재무제표' vs the CSV button whose
    label is '⬇ 재무제표 CSV (원 단위, 선택 구간)'). Same verify+retry pattern
    as set_radio — see its docstring for why a single click isn't trusted."""
    ok = _click_radio_verified(page, tab_label)
    time.sleep(0.3 if ok else 0)


def has_exception_box(page) -> bool:
    if page.locator('[data-testid="stException"]').count() > 0:
        return True
    body = page.inner_text("body")
    return ("Traceback (most recent call last)" in body) or ("StreamlitAPIException" in body)


def extend_slider_full_range(page) -> bool:
    sliders = page.locator('[role="slider"]')
    if sliders.count() < 2:
        return False
    left, right = sliders.nth(0), sliders.nth(1)
    try:
        left.scroll_into_view_if_needed(timeout=5000)
        box = left.bounding_box()
        if not box:
            return False
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx - 900, cy, steps=20)
        time.sleep(0.15)
        page.mouse.up()
        time.sleep(0.5)

        box2 = right.bounding_box()
        if box2:
            cx2, cy2 = box2["x"] + box2["width"] / 2, box2["y"] + box2["height"] / 2
            page.mouse.move(cx2, cy2)
            page.mouse.down()
            page.mouse.move(cx2 + 900, cy2, steps=20)
            time.sleep(0.15)
            page.mouse.up()
            time.sleep(0.5)
        return True
    except Exception:
        return False


def download_fin_csv(page):
    """Returns (df_or_None, detail_str). Waits for the button to actually be
    visible+enabled (not just present in DOM) before clicking, and retries
    once after a short pause — a Streamlit rerun can leave the button
    momentarily stale/detached right after a radio/slider change."""
    last_err = "button not found"
    for attempt in range(2):
        btns = page.locator('button:has-text("재무제표 CSV")')
        if btns.count() == 0:
            last_err = "button not present in DOM"
            time.sleep(1.0)
            continue
        try:
            btns.first.wait_for(state="visible", timeout=6000)
            btns.first.scroll_into_view_if_needed(timeout=5000)
            with page.expect_download(timeout=15000) as dl_info:
                btns.first.evaluate("el => el.click()")
            download = dl_info.value
            tmp_path = download.path()
            with open(tmp_path, "rb") as fh:
                data = fh.read()
            return pd.read_csv(io.StringIO(data.decode("utf-8-sig"))), "ok"
        except Exception as exc:  # noqa: BLE001
            last_err = f"attempt {attempt+1} failed: {exc}"
            time.sleep(1.2)
    return None, last_err


def get_header_text(page) -> str:
    """Company identity subheader ('기업명(종목코드) · corp_code · 시장(주n)') in the
    MAIN content area. A naive nth-index over ALL stHeading elements is wrong
    because the sidebar (TJ Finance title, 기업 검색, 표시 옵션) also emits
    stHeading nodes ahead of the main-content ones — this previously caused
    DS-8 to compare against the sidebar's "기업 검색" label instead. Exclude the
    sidebar subtree explicitly, then take the LAST heading in main content
    (main content order: '기업 시각화' st.header, then the company identity
    st.subheader — identity is always last of the two)."""
    try:
        main_headings = page.locator(
            '[data-testid="stAppViewContainer"] [data-testid="stHeading"]')
        sidebar_headings = page.locator(
            '[data-testid="stSidebar"] [data-testid="stHeading"]')
        n_main, n_sidebar = main_headings.count(), sidebar_headings.count()
        texts = [main_headings.nth(i).inner_text() for i in range(n_main)]
        # sidebar headings are also matched by the broader stAppViewContainer selector
        # in some Streamlit DOM layouts; filter them out by text-set difference.
        sidebar_texts = {sidebar_headings.nth(i).inner_text() for i in range(n_sidebar)}
        content_only = [t for t in texts if t not in sidebar_texts]
        for t in reversed(content_only):
            if "·" in t:  # identity line always contains the ' · corp_code · market' separator
                return t
        if content_only:
            return content_only[-1]
    except Exception:
        pass
    return page.inner_text("body")[:200]


# ───────────────────────── per-company-combo run ──────────────────────────

def run_combo(page, corp: dict, grain: str, stmt: str, grain_label: str, stmt_label: str,
              combo_key: str) -> tuple[list, list, list]:
    """Returns (sweep_rows, gap_rows, diff_rows) for this corp x combo."""
    now = datetime.now().isoformat(timespec="seconds")
    sweep_rows, gap_rows, diff_rows = [], [], []
    company = corp["corp_name"]
    corp_code = corp["corp_code"]

    def sw(tab, check_id, result, detail=""):
        sweep_rows.append([company, corp_code, corp.get("stock_code", ""), corp.get("market", ""),
                           combo_key, tab, check_id, result, detail, "", now])

    set_radio(page, [], stmt_label)
    set_radio(page, [], grain_label)
    time.sleep(0.6)

    if has_exception_box(page):
        sw("재무제표", "DS-1", "FAIL", "exception box / traceback visible after combo toggle")
        return sweep_rows, gap_rows, diff_rows
    body = page.inner_text("body")
    if len(body.strip()) < 200:
        sw("재무제표", "DS-1", "FAIL", "page body suspiciously blank")
        return sweep_rows, gap_rows, diff_rows
    sw("재무제표", "DS-1", "PASS", "")

    # Guard: some corps have zero rows in std_financials_v2 for EITHER basis
    # (e.g. fund/REIT-type filers) — company_page.py's `if not series:
    # st.warning(...); return` means the TABS radio group never renders at
    # all in that case. Without this guard, click_tab()/download_fin_csv()
    # below would hang on their 20s selector timeout per combo (confirmed:
    # 088980 맥쿼리인프라 cost ~100s across 4 combos before this guard).
    if "표준화" in body and "데이터가 없습니다" in body:
        sw("재무제표", "DS-1/NA", "NA", "std_financials_v2/calendar_financials 데이터 0건 "
           "(데이터결함, 앱버그 아님) — 앱이 경고문구를 정상 표시하고 탭 자체를 렌더하지 않음")
        return sweep_rows, gap_rows, diff_rows

    # DS-8 header identity
    # Retry-before-fail: under heavy concurrent load (multiple shard workers +
    # Streamlit instances sharing the same machine/DB), the fixed 0.6s
    # post-combo-toggle sleep above occasionally isn't enough for the
    # company-identity subheader to finish re-rendering, even though the
    # underlying data (financial table, tabs) is already correct — confirmed
    # by shard3 spot-check: 9 companies FAILed here during a 6-shard
    # concurrent run, but the exact same company+combo re-checked in
    # isolation (no concurrent load) passed immediately. Give it one more
    # short wait before declaring a real FAIL, so the check reflects the
    # rendered page rather than test-harness scheduling noise.
    header = get_header_text(page)
    expect_bits = [company]
    if corp.get("stock_code"):
        expect_bits.append(str(corp["stock_code"]))
    if corp.get("market"):
        expect_bits.append(str(corp["market"]))
    missing = [b for b in expect_bits if b not in header]
    if missing:
        time.sleep(1.2)
        header = get_header_text(page)
        missing = [b for b in expect_bits if b not in header]
    if missing:
        sw("상단", "DS-8", "FAIL", f"header missing {missing} — header={header[:120]!r}")
    else:
        sw("상단", "DS-8", "PASS", "")

    # DS-4 substitution caption (별도/연결 대체)
    if "데이터 없음" in body and "표시" in body:
        sw("상단", "DS-4", "PASS", "substitution caption present")

    # DS-7 badges (best-effort presence scan, informational)
    badge_hits = [tok for tok in ("✅", "🔎", "⚠") if tok in body]
    sw("상단", "DS-7", "PASS" if badge_hits else "NA", f"badges seen: {badge_hits}")

    # ── 재무제표 tab: extend slider, download CSV, cross-check ──
    extended = extend_slider_full_range(page)
    df, dl_detail = download_fin_csv(page)
    if df is None:
        sw("재무제표", "CV-3", "FAIL", f"CSV download failed: {dl_detail}")
        try:
            shot = os.path.join(SHOTS_DIR, f"{corp.get('stock_code') or corp_code}_{combo_key}_CV3FAIL.png")
            page.screenshot(path=shot, full_page=True)
        except Exception:
            pass
    else:
        sw("재무제표", "CV-3", "PASS", f"rows={len(df)} cols={len(df.columns)} slider_extended={extended}")
        _cross_check(df, corp, grain, stmt, combo_key, now, gap_rows, diff_rows, sweep_rows, company, corp_code)

    # ── 지표 tab: presence / no-crash ──
    click_tab(page, "📊 지표")
    if has_exception_box(page):
        sw("지표", "DS-1", "FAIL", "exception box on 지표 tab")
    else:
        body2 = page.inner_text("body")
        # Retry-before-fail: same rationale as the DS-8 header check above —
        # the 지표 tab's default-metric render occasionally lags the fixed
        # 0.3s post-tab-click sleep under heavy concurrent load (confirmed
        # via shard3 spot-check, same as DS-8).
        if "매출액" not in body2 and "영업이익" not in body2:
            time.sleep(1.2)
            body2 = page.inner_text("body")
        sw("지표", "CV-6", "PASS" if "매출액" in body2 or "영업이익" in body2 else "FAIL",
           "default metric selection visible" if "매출액" in body2 else "default metrics not found")
    click_tab(page, "📑 재무제표")  # reset for next combo iteration

    return sweep_rows, gap_rows, diff_rows


def _cross_check(df, corp, grain, stmt, combo_key, now, gap_rows, diff_rows, sweep_rows, company, corp_code):
    df = df.set_index(["구분", "항목"]) if "구분" in df.columns else df.set_index(df.columns[0])
    period_cols = [c for c in df.columns if c not in ("구분", "항목")]

    for label, dbkey in METRIC_MAP.items():
        try:
            row = df.xs(("손익계산서", label))
        except Exception:
            continue
        # UI-visible periods with non-null value, in chronological column order (CSV is newest->oldest)
        chrono_cols = list(reversed(period_cols))
        vals = {c: row[c] for c in chrono_cols}
        non_null_idx = [i for i, c in enumerate(chrono_cols) if pd.notna(vals[c])]
        if len(non_null_idx) < 2:
            continue
        first_i, last_i = non_null_idx[0], non_null_idx[-1]
        mid_missing = [chrono_cols[i] for i in range(first_i, last_i + 1) if pd.isna(vals[chrono_cols[i]])]

        if grain == "annual":
            db_all = db_annual_all_years(corp_code, stmt)
            for period in mid_missing:
                fy = int(period)
                db_row = db_all.get(fy)
                db_val = db_row.get(dbkey) if db_row else None
                cls = "app_bug_mid_gap" if db_val is not None else "data_gap"
                gap_rows.append([company, corp_code, combo_key, dbkey, period, cls,
                                 f"UI blank, DB={db_val}", now])
            for i in range(first_i, last_i + 1):
                period = chrono_cols[i]
                v = vals[period]
                if pd.isna(v):
                    continue
                fy = int(period)
                db_row = db_annual_row(corp_code, stmt, fy)
                db_val = db_row.get(dbkey) if db_row else None
                if db_val is None:
                    continue
                diff_pct = abs(float(v) - float(db_val)) / max(abs(float(db_val)), 1.0)
                if diff_pct > TOL_REL:
                    diff_rows.append([company, corp_code, combo_key, period, dbkey, v, db_val,
                                      f"{diff_pct*100:.3f}%", now])
        else:  # quarter
            db_all = db_quarter_all(corp_code, stmt)

            def parse_q(p):
                y, q = p.split()
                return int(y), q

            for period in mid_missing:
                y, q = parse_q(period)
                db_row = db_all.get((y, q))
                db_val = db_row.get(dbkey) if db_row else None
                cls = "app_bug_mid_gap" if db_val is not None else "data_gap"
                gap_rows.append([company, corp_code, combo_key, dbkey, period, cls,
                                 f"UI blank, DB={db_val}", now])
            for i in range(first_i, last_i + 1):
                period = chrono_cols[i]
                v = vals[period]
                if pd.isna(v):
                    continue
                y, q = parse_q(period)
                db_row = db_quarter_row(corp_code, stmt, y, q)
                db_val = db_row.get(dbkey) if db_row else None
                if db_val is None:
                    continue
                diff_pct = abs(float(v) - float(db_val)) / max(abs(float(db_val)), 1.0)
                if diff_pct > TOL_REL:
                    diff_rows.append([company, corp_code, combo_key, period, dbkey, v, db_val,
                                      f"{diff_pct*100:.3f}%", now])
    sweep_rows.append([company, corp_code, corp.get("stock_code", ""), corp.get("market", ""),
                       combo_key, "재무제표", "DS-2/DS-3", "DONE",
                       f"cross-check completed for {list(METRIC_MAP)}", "", now])


def sweep_one_company(page, corp: dict, done: set, take_screenshot_budget: list) -> float:
    t0 = time.time()
    corp_code = corp["corp_code"]
    query = corp.get("stock_code") or corp["corp_code"]
    dismiss_cold_start_dialog(page)
    if not select_company(page, str(query)):
        # fall back to name search
        if not select_company(page, corp["corp_name"]):
            rows = [[corp["corp_name"], corp_code, corp.get("stock_code", ""), corp.get("market", ""),
                     "ALL", "sidebar", "SB-1", "FAIL", "company not found via search",
                     "", datetime.now().isoformat(timespec="seconds")]]
            _append_rows(SWEEP_CSV, SWEEP_HEADER, rows)
            return time.time() - t0

    for grain, stmt, grain_label, stmt_label in COMBOS:
        combo_key = f"{grain_label}x{stmt_label}"
        if (corp_code, combo_key) in done:
            continue
        combo_t0 = time.time()
        try:
            sweep_rows, gap_rows, diff_rows = run_combo(
                page, corp, grain, stmt, grain_label, stmt_label, combo_key)
        except Exception as exc:  # noqa: BLE001
            sweep_rows = [[corp["corp_name"], corp_code, corp.get("stock_code", ""), corp.get("market", ""),
                          combo_key, "재무제표", "DS-1", "FAIL",
                          f"script exception: {exc}", "", datetime.now().isoformat(timespec="seconds")]]
            gap_rows, diff_rows = [], []
            traceback.print_exc()
        combo_elapsed = time.time() - combo_t0

        # screenshot only on anomaly, budget-limited random audit sample handled by caller
        anomalies = [r for r in sweep_rows if r[7] == "FAIL"] + gap_rows
        if anomalies or (take_screenshot_budget and take_screenshot_budget[0] > 0):
            try:
                shot = os.path.join(SHOTS_DIR, f"{corp.get('stock_code') or corp_code}_{combo_key}_finstmt.png")
                page.screenshot(path=shot, full_page=True)
                if take_screenshot_budget:
                    take_screenshot_budget[0] -= 1
            except Exception:
                pass

        _append_rows(SWEEP_CSV, SWEEP_HEADER, sweep_rows)
        _append_rows(GAPS_CSV, GAPS_HEADER, gap_rows)
        _append_rows(DIFFS_CSV, DIFFS_HEADER, diff_rows)
        with open(TIMING_CSV, "a", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow([corp_code, combo_key, "combo_total", f"{combo_elapsed:.2f}",
                                    datetime.now().isoformat(timespec="seconds")])
        done.add((corp_code, combo_key))

    return time.time() - t0


def load_companies_from_csv(path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_random_companies(n: int, exclude: set) -> list[dict]:
    sql = """
        SELECT corp_code, corp_name, stock_code, market, fiscal_month
        FROM corporations
        WHERE is_active=TRUE AND stock_code IS NOT NULL
        ORDER BY random() LIMIT :n
    """
    with get_session() as s:
        rows = s.execute(text(sql), {"n": n * 2}).mappings().fetchall()
    out = []
    for r in rows:
        if r["corp_code"] in exclude:
            continue
        out.append(dict(r))
        if len(out) >= n:
            break
    return out


def main():
    global BASE_URL, SWEEP_CSV, GAPS_CSV, DIFFS_CSV, TIMING_CSV

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="CSV with corp_code,corp_name,stock_code,market columns")
    ap.add_argument("--random", type=int, default=0, help="add N random companies")
    ap.add_argument("--audit-screenshots", type=int, default=50,
                    help="random audit screenshot budget across whole run")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--port", type=int, default=8501,
                    help="Streamlit instance port this shard/process talks to "
                         "(each parallel shard should run its OWN Streamlit "
                         "instance on its own port — sharing one instance "
                         "across concurrent Playwright sessions is untested "
                         "and not recommended)")
    ap.add_argument("--shard-tag", default="",
                    help="if set, all four output CSVs are written to "
                         "docs/qa/results/shards/<file>_<tag>.csv instead of "
                         "the unsuffixed docs/qa/results/<file>.csv — REQUIRED "
                         "for concurrent shards so they never write to the "
                         "same file. Leave unset for the original single-"
                         "process pilot behavior.")
    args = ap.parse_args()

    BASE_URL = f"http://localhost:{args.port}"
    if args.shard_tag:
        os.makedirs(SHARDS_DIR, exist_ok=True)
        SWEEP_CSV = os.path.join(SHARDS_DIR, f"sweep_all_companies_{args.shard_tag}.csv")
        GAPS_CSV = os.path.join(SHARDS_DIR, f"mid_gaps_{args.shard_tag}.csv")
        DIFFS_CSV = os.path.join(SHARDS_DIR, f"value_diffs_{args.shard_tag}.csv")
        TIMING_CSV = os.path.join(SHARDS_DIR, f"sweep_timing_{args.shard_tag}.csv")

    print(f"[{args.shard_tag or 'no-shard'}] BASE_URL={BASE_URL} "
          f"SWEEP_CSV={SWEEP_CSV}")

    _ensure_files()
    done = _done_combos()

    companies = []
    seen_codes = set()
    if args.input:
        for c in load_companies_from_csv(args.input):
            if c["corp_code"] not in seen_codes:
                companies.append(c)
                seen_codes.add(c["corp_code"])
    if args.random:
        for c in load_random_companies(args.random, seen_codes):
            companies.append(c)
            seen_codes.add(c["corp_code"])

    print(f"companies queued: {len(companies)}")
    budget = [args.audit_screenshots]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1400})
        page.set_default_timeout(20000)
        for i, corp in enumerate(companies):
            corp_code = corp["corp_code"]
            all_done = all((corp_code, f"{gl}x{sl}") in done for _, _, gl, sl in COMBOS)
            if all_done:
                print(f"[{i+1}/{len(companies)}] {corp['corp_name']} — already done, skip")
                continue
            print(f"[{i+1}/{len(companies)}] {corp['corp_name']} ({corp.get('stock_code')}) ...", flush=True)
            try:
                elapsed = sweep_one_company(page, corp, done, budget)
                print(f"    done in {elapsed:.1f}s")
            except Exception as exc:  # noqa: BLE001
                print(f"    FATAL for {corp['corp_name']}: {exc}")
                traceback.print_exc()
                try:
                    page.close()
                except Exception:
                    pass
                page = browser.new_page(viewport={"width": 1600, "height": 1400})
                page.set_default_timeout(20000)
        browser.close()

    print("sweep run complete.")


if __name__ == "__main__":
    main()
