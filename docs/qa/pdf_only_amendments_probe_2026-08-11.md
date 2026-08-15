# Phase 1-9 — PDF-only 정정 필링 실측 (2026-08-11)

> 계획서 §1-9(정정 PDF 쌍 비율 실측, is_final=False 297건 포함 스코프). 스크립트 = `scripts/probe_pdf_only_amendments.py`(읽기 전용).

**★사전 발견**: `filings.superseded_by`는 프로젝트 전체(188,296건) 중 0건 채워짐 — 정정 계보 추적에 쓸 수 없는 죽은 컬럼. 대신 (corp_code, report_type, fiscal_year, fiscal_period, is_final=True) 그룹키로 같은 기간 최종본을 찾아 재구성했다(아래 결과는 이 방식 기준). §4에서 언급한 `amended_by` 계보는 XML 파이프라인에도 없는 **신규 스키마 개념** — Phase 2 설계 시 반영 필요.

**is_final=False PDF-only 필링(그룹조인 기준) 총 506건**

| 분류 | 건수 | 비율 |
|---|---|---|
| 최종본을 못 찾음(orphan) | 0 | 0.0% |
| 최종본이 XML 보유(이미 커버됨) | 200 | 39.5% |
| 최종본도 PDF-only(진짜 정정쌍) | 306 | 60.5% |

## 3분류(FULL_REPORT/PARTIAL_COVER/NON_FINANCIAL) 실측 적용 결과

표본 30쌍(orig=is_final=False 필링, final=같은 기간 최종본)

| orig_rcept | final_rcept | FY | period | orig_class | final_class | orig_report_nm |
|---|---|---|---|---|---|---|
| 20180814002845 | 20180830000453 | 2018 | Q1 | full_report | full_report | [기재정정]분기보고서 (2018.03) |
| 20160517000128 | 20160718000440 | 2016 | Q1 | full_report | full_report | [기재정정]분기보고서 (2016.03) |
| 20180816000301 | 20190812000378 | 2018 | H1 | full_report | full_report | [기재정정]반기보고서 (2018.06) |
| 20150902000296 | 20151126000316 | 2015 | H1 | full_report | full_report | [기재정정]반기보고서 (2015.06) |
| 20001114000802 | 20001115000020 | 2000 | Q3 | non_financial | full_report | 분기보고서 (2000.09) |
| 20170814002320 | 20190417000552 | 2017 | H1 | full_report | full_report | [기재정정]반기보고서 (2017.06) |
| 20150813001052 | 20150813001066 | 2015 | H1 | full_report | full_report | [기재정정]반기보고서 (2015.06) |
| 20160509001709 | 20160509001754 | 2016 | Q1 | full_report | full_report | [기재정정]분기보고서 (2016.03) |
| 20171103000526 | 20180314000554 | 2017 | H1 | full_report | full_report | [기재정정]반기보고서 (2017.06) |
| 20040421000277 | 20040630000037 | 2003 | FY | full_report | full_report | [첨부정정]사업보고서 (2003.12) |
| 20160816001265 | 20180419000528 | 2016 | H1 | full_report | full_report | [기재정정]반기보고서 (2016.06) |
| 20180118000362 | 20180119000236 | 2017 | Q1 | full_report | full_report | [기재정정]분기보고서 (2017.03) |
| 20001113000165 | 20001114000638 | 2000 | Q3 | non_financial | full_report | 분기보고서 (2000.09) |
| 20001114000363 | 20001114000708 | 2000 | Q3 | non_financial | full_report | 분기보고서 (2000.09) |
| 20001114001018 | 20001215000166 | 2001 | H1 | non_financial | full_report | 반기보고서 (2000.09) |
| 20001113000371 | 20001113000372 | 2000 | Q3 | non_financial | non_financial | 분기보고서 (2000.09) |
| 20170529000254 | 20171218000231 | 2017 | Q1 | full_report | full_report | [기재정정]분기보고서 (2017.03) |
| 20180118000372 | 20180119000240 | 2017 | Q3 | full_report | full_report | [기재정정]분기보고서 (2017.09) |
| 20170215000319 | 20170217000062 | 2017 | H1 | full_report | full_report | [기재정정]반기보고서 (2016.12) |
| 20001114000527 | 20001114000529 | 2000 | Q3 | non_financial | non_financial | 분기보고서 (2000.09) |
| 20001114000619 | 20001114000627 | 2000 | Q3 | non_financial | non_financial | 분기보고서 (2000.09) |
| 20001113000019 | 20001116000047 | 2000 | Q3 | non_financial | full_report | 분기보고서 (2000.09) |
| 20160518000210 | 20160603000306 | 2016 | Q1 | full_report | full_report | [기재정정]분기보고서 (2016.03) |
| 20161118000393 | 20161229000216 | 2015 | H1 | full_report | full_report | [기재정정]반기보고서 (2015.06) |
| 20001114000225 | 20001115000025 | 2000 | Q3 | non_financial | full_report | 분기보고서 (2000.09) |
| 20001113000472 | 20001204000059 | 2000 | Q3 | non_financial | full_report | 분기보고서 (2000.09) |
| 20190531001686 | 20190531002132 | 2019 | Q1 | full_report | full_report | [기재정정]분기보고서 (2019.03) |
| 20001114000493 | 20001114000508 | 2000 | Q3 | non_financial | non_financial | 분기보고서 (2000.09) |
| 20001113000099 | 20001113000364 | 2000 | Q3 | full_report | full_report | [기재정정]분기보고서 (2000.09) |
| 20001114000110 | 20001116000008 | 2001 | H1 | non_financial | non_financial | 반기보고서 (2000.09) |

**orig 분류 분포**: {'full_report': 18, 'non_financial': 12}

**final 분류 분포**: {'full_report': 25, 'non_financial': 5}

## 결론 (초안 — 사용자 검토 후 Phase 2 착수)

_이 절은 위 표 결과를 보고 사람이 채운다._
