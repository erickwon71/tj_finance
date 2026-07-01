"""
보고서 수집·DB화 페이지.

실행일 기준 최근 등록된 정기공시(사업/반기/분기)를 탐지 → 신규 다운로드 → 파싱·표준화·
분기·달력 반영을 **원클릭 순차 흐름**으로 진행하고 단계별 진행상황을 표시한다.
기존 파이프라인(sync_filings·run_downloads·process_corp) 인프로세스 재사용.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.data import collect


def _dashboard() -> None:
    s = collect.collection_status()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("활성 보통주", f"{s['active_corps']:,}")
    c2.metric("정기공시(filings)", f"{s['filings']:,}")
    c3.metric("다운로드(xml)", f"{s['downloaded']:,}")
    c4.metric("표준화 기업", f"{s['std_corps']:,}")
    lf = s.get("latest_filed")
    pend = s.get("pending") or 0
    st.caption(f"최신 공시 접수일: **{lf}** · 다운로드 대기(pending/failed): **{pend:,}**")


def _universe_section() -> None:
    """상장 유니버스 갱신 — 신규 상장 반영 + 상장폐지·제외 비활성화, 두 목록 표시."""
    st.subheader("① 상장 유니버스 갱신 (신규 상장 · 상장폐지 반영)")
    st.caption("KRX 상장 목록 기준으로 **신규 상장** 기업을 대상에 추가하고, 목록에서 빠진 "
               "기업(**상장폐지·제외**)을 비활성화합니다. 신규 공시 수집 전에 실행하면 신규 상장사도 포함됩니다.")

    if not st.button("🔁 유니버스 갱신 실행", key="btn_refresh_universe"):
        return

    with st.status("KRX 상장 목록 동기화 중… (수십 초 소요)", expanded=True) as status:
        try:
            r = collect.refresh_universe()
        except Exception as exc:  # noqa: BLE001
            status.update(label=f"갱신 실패: {exc}", state="error")
            st.error(str(exc))
            return

        c1, c2, c3 = st.columns(3)
        c1.metric("현재 대상(활성)", f"{r.get('final_count', 0):,}")
        c2.metric("신규 반영", f"{r.get('new_count', 0):,}")
        c3.metric("제외(비활성)", f"{r.get('deactivated', 0):,}")

        new = r.get("new_corps") or []
        deact = r.get("deactivated_corps") or []
        with st.expander(f"🆕 신규 기업 {len(new)}개", expanded=bool(new)):
            if new:
                st.dataframe(pd.DataFrame(new), hide_index=True, width="stretch")
            else:
                st.caption("신규 상장/재등록 기업 없음")
        with st.expander(f"🚫 제외 기업 {len(deact)}개", expanded=bool(deact)):
            if deact:
                st.dataframe(pd.DataFrame(deact), hide_index=True, width="stretch")
            else:
                st.caption("상장폐지/제외 기업 없음")

        status.update(
            label=f"완료 — 신규 {r.get('new_count', 0)} · 제외 {r.get('deactivated', 0)}",
            state="complete")


def _run_flow(days: int) -> None:
    """① 탐지 → ② 동기화 → ③ 다운로드 → ④ 파싱·표준화. 단계별 st.status 표시."""
    from collector.filing_collector import sync_filings
    from collector.downloader import run_downloads
    from run import process_corp  # E→R→S→분기→달력 per-corp 오케스트레이션

    with st.status("신규 공시 수집 진행 중…", expanded=True) as status:
        # ① 탐지
        st.write(f"**①** 최근 {days}일 DART 정기공시 조회…")
        disc = collect.discover_recent_corps(days)
        corps = disc["corps"]
        st.write(f"  · 기간 {disc['window']} · 정기공시 {disc['total_filings']:,}건 "
                 f"→ 활성 보통주 **{len(corps)}개** 기업")
        if not corps:
            status.update(label="신규 공시 없음 — 종료", state="complete")
            return

        # ② 공시목록 동기화(+다운로드 큐 생성)
        # force=True: 이미 동기화된 기업이라도 *새 공시* 재확인(일일 증분). discover 로 이미
        # 최근 공시 있는 기업으로 좁혀놨으므로 그 기업들만 강제 재동기화 = 저렴.
        st.write(f"**②** 공시목록 동기화 ({len(corps)}개 기업, 신규 재확인)…")
        r1 = sync_filings(corp_codes=corps, force=True)
        st.write(f"  · 동기화: {r1.get('processed', 0)}/{r1.get('total_corps', 0)}개 기업 "
                 f"(API {r1.get('api_calls', 0)}콜)")

        # ③ 신규 다운로드
        st.write("**③** 신규 보고서 다운로드…")
        r2 = run_downloads(only_corp_codes=corps)
        st.write(f"  · 큐 {r2.get('total_queued', 0)} · 완료 **{r2.get('completed', 0)}** · "
                 f"실패 {r2.get('failed', 0)} · 스킵 {r2.get('skipped', 0)}")

        # ④ 파싱·표준화·분기·달력
        affected = collect.needs_standardize_corps(only=corps)
        st.write(f"**④** 파싱·표준화·분기·달력 반영 — 대상 **{len(affected)}개** 기업…")
        if affected:
            from collector.db import get_session
            prog = st.progress(0.0)
            agg = {"e_facts": 0, "s": 0, "q": 0, "c": 0, "errors": 0}
            for i, corp in enumerate(affected, 1):
                try:
                    with get_session() as session:
                        out = process_corp(session, corp)
                        for k in ("e_facts", "s", "q", "c"):
                            agg[k] += out[k]
                        session.commit()
                except Exception as exc:  # noqa: BLE001
                    agg["errors"] += 1
                    st.write(f"  · ⚠ {corp} 실패: {exc}")
                prog.progress(i / len(affected))
            st.write(f"  · fact {agg['e_facts']:,} · std_v2 {agg['s']:,} · "
                     f"이산분기 {agg['q']:,} · 달력 {agg['c']:,} · 오류 {agg['errors']}")

        status.update(label=f"완료 — 신규 {len(corps)}개 기업 수집·반영", state="complete")


def render() -> None:
    st.header("🗂 보고서 수집 · DB화")
    st.caption("실행일 기준 신규 정기공시(사업/반기/분기)를 탐지 → 다운로드 → 파싱·표준화·"
               "분기/달력 반영까지 한 번에 진행합니다.")

    _dashboard()
    st.divider()

    _universe_section()
    st.divider()

    st.subheader("② 신규 공시 수집")
    c1, c2 = st.columns([1, 2])
    days = int(c1.number_input("탐지 기간(일)", min_value=1, max_value=90, value=7, step=1,
                               help="실행일로부터 최근 N일 내 등록된 정기공시를 확인"))
    run = c2.button("🔄 신규 공시 수집 실행", type="primary", width="stretch")

    st.caption("※ 수집 중에는 이 페이지가 잠시 멈춥니다(완료 후 자동 갱신). DART API·다운로드는 "
               "네트워크에 따라 시간이 걸릴 수 있습니다.")

    if run:
        try:
            _run_flow(days)
        except Exception as exc:  # noqa: BLE001
            st.error(f"수집 중 오류: {exc}")
        st.divider()
        st.subheader("갱신된 현황")
        _dashboard()
