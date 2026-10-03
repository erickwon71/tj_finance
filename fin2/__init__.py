"""
fin2 — report→DB 표준화 계층의 병행 재구축 패키지.

기존(analyzer/aggregator 기반) 파이프라인을 손상시키지 않고 새 스키마로 단계적으로 재구축한 패키지.
(2026-10-03: 중간 산출물 fact_v2 / statement_source / std_financials_v2 는 모두 폐기, 현재는 report_lines → std_financials_v3.)
golden(정답 고정) + parity(현 파이프라인 무회귀) 게이트로 회귀를 차단한다.

설계 문서: docs/fin2_rebuild_plan_2026-05-31.md
"""
