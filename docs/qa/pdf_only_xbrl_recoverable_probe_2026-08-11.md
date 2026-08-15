# Phase 1-2 — PDF-only ifrs.do XBRL 회수가능성 실측 (2026-08-11)

> 계획서 §1-2(2015-2019 몰림 원인 최우선 조사) 실행 결과. 스크립트 = `scripts/probe_pdf_only_xbrl_recoverable.py`(읽기 전용, DB 미기록).

## pre2015 (표본 40건)

**XBRL 회수가능 0/40건(0.0%), 조사오류 0건**

| rcept_no | corp_name | FY | report_type | document.xml | xbrl_recoverable | size |
|---|---|---|---|---|---|---|
| 20080507000270 | 와이지-원 | 2007 | annual | error_014 | False | 0 |
| 20030515001744 | 현대코퍼레이션 | 2002 | annual | error_014 | False | 0 |
| 20130814001451 | 삼성증권 | 2013 | quarter | error_014 | False | 0 |
| 20001113000416 | DH오토넥스 | 2000 | quarter | error_014 | False | 0 |
| 20001113000057 | 삼보산업 | 2000 | quarter | error_014 | False | 0 |
| 20001115000043 | 카페24 | 2000 | quarter | error_014 | False | 0 |
| 20001114000566 | 그래디언트 | 2000 | quarter | error_014 | False | 0 |
| 20001114000117 | 대원제약 | 2000 | quarter | error_014 | False | 0 |
| 20001114000421 | LG | 2000 | quarter | error_014 | False | 0 |
| 20110920000141 | 케이바이오랩스 | 2011 | half | error_014 | False | 0 |
| 20130925000181 | 한국가스공사 | 2013 | half | error_014 | False | 0 |
| 20001229000162 | 인터엠 | 2000 | annual | error_014 | False | 0 |
| 20001114000719 | 뉴인텍 | 2000 | quarter | error_014 | False | 0 |
| 20001114000648 | 한솔테크닉스 | 2000 | quarter | error_014 | False | 0 |
| 20001229000049 | 디지틀조선 | 2000 | annual | error_014 | False | 0 |
| 20001128000065 | SG글로벌 | 2000 | quarter | error_014 | False | 0 |
| 20001114000534 | 우리기술 | 2000 | quarter | error_014 | False | 0 |
| 20001114000449 | HLB파나진 | 2001 | quarter | error_014 | False | 0 |
| 20001113000118 | 모헨즈 | 2000 | quarter | error_014 | False | 0 |
| 20001114000890 | 금호전기 | 2000 | quarter | error_014 | False | 0 |
| 20001114000153 | 한익스프레스 | 2000 | quarter | error_014 | False | 0 |
| 20070705000145 | 한국컴퓨터 | 2006 | annual | error_014 | False | 0 |
| 20000503000073 | 현대자동차 | 1999 | annual | error_014 | False | 0 |
| 20030404000085 | 대호에이엘 | 2002 | annual | error_014 | False | 0 |
| 20000928000123 | 마크로젠 | 2000 | annual | error_014 | False | 0 |
| 20001113000265 | SP삼화 | 2000 | quarter | error_014 | False | 0 |
| 20001114000690 | SK텔레콤 | 2000 | quarter | error_014 | False | 0 |
| 20001114000005 | 아진전자부품 | 2000 | quarter | error_014 | False | 0 |
| 20060811000565 | 해성산업 | 2006 | half | error_014 | False | 0 |
| 20001113000234 | 팜스코 | 2000 | quarter | error_014 | False | 0 |
| 20050429001269 | CJ ENM | 2004 | annual | error_014 | False | 0 |
| 20120521000154 | 대원강업 | 2012 | quarter | error_014 | False | 0 |
| 20001114000748 | 광동제약 | 2000 | quarter | error_014 | False | 0 |
| 20100331002245 | 씨씨에스 | 2009 | annual | error_014 | False | 0 |
| 20001114000851 | 미래에셋증권 | 2001 | half | error_014 | False | 0 |
| 20001111000031 | 우리기술투자 | 2000 | quarter | error_014 | False | 0 |
| 20001113000227 | 대구백화점 | 2001 | half | error_014 | False | 0 |
| 20001113000252 | 신라교역 | 2000 | quarter | error_014 | False | 0 |
| 20001113000143 | 티케이지애강 | 2000 | quarter | error_014 | False | 0 |
| 20001114000727 | 디씨엠 | 2000 | quarter | error_014 | False | 0 |

## 2015+ (표본 40건)

**XBRL 회수가능 33/40건(82.5%), 조사오류 0건**

| rcept_no | corp_name | FY | report_type | document.xml | xbrl_recoverable | size |
|---|---|---|---|---|---|---|
| 20191114002657 | 디와이피엔에프 | 2019 | quarter | error_014 | True | 201746 |
| 20180820000270 | 포스코스틸리온 | 2018 | half | error_014 | True | 203883 |
| 20190515001230 | 트리니티항공 | 2019 | quarter | error_014 | True | 208276 |
| 20171109000076 | HC보광산업 | 2017 | half | error_014 | True | 78153 |
| 20170628000279 | 수산아이앤티 | 2017 | quarter | error_014 | True | 66407 |
| 20150817000268 | 와토스코리아 | 2015 | quarter | error_014 | True | 75963 |
| 20180615000490 | 동양생명 | 2018 | quarter | error_014 | False | 0 |
| 20190123000280 | DMS | 2018 | quarter | error_014 | True | 203953 |
| 20151125000357 | 시너지이노베이션 | 2015 | quarter | error_014 | True | 173309 |
| 20210317000005 | 한솔케미칼 | 2020 | annual | error_014 | False | 0 |
| 20150521000535 | 남양유업 | 2014 | quarter | error_014 | True | 144304 |
| 20180621000443 | 상지건설 | 2018 | quarter | error_014 | True | 180179 |
| 20181114000380 | 온타이드 | 2018 | quarter | error_014 | True | 192054 |
| 20230316001209 | 한화솔루션 | 2022 | annual | error_014 | False | 0 |
| 20200214001123 | 디에이테크놀로지 | 2019 | half | error_014 | True | 220767 |
| 20190809000488 | 현대코퍼레이션 | 2019 | half | error_014 | True | 205455 |
| 20171205000323 | 피제이전자 | 2017 | quarter | error_014 | True | 92890 |
| 20151210000346 | 누리플랜 | 2015 | quarter | error_014 | True | 74298 |
| 20151211000341 | 케이피티유 | 2015 | quarter | error_014 | True | 61459 |
| 20171115000039 | 폴라리스세원 | 2017 | quarter | error_014 | True | 92066 |
| 20190222001680 | 텔콘RF제약 | 2018 | quarter | error_014 | True | 188164 |
| 20191204000050 | 대산F&B | 2019 | quarter | error_014 | True | 202464 |
| 20190401003611 | 지누스 | 2018 | quarter | error_014 | True | 191339 |
| 20171116000082 | 사조오양 | 2017 | quarter | error_014 | True | 105108 |
| 20190816000196 | 키다리스튜디오 | 2019 | half | error_014 | True | 108178 |
| 20150206000004 | 현대리바트 | 2013 | quarter | error_014 | True | 133636 |
| 20170515004139 | 한국컴퓨터 | 2017 | quarter | error_014 | True | 127747 |
| 20150826000195 | 대한뉴팜 | 2015 | half | error_014 | True | 74059 |
| 20150515002503 | 대호특수강 | 2015 | quarter | error_014 | True | 73470 |
| 20170905000043 | 스타플렉스 | 2017 | half | error_014 | True | 114905 |
| 20180419000535 | 뉴온 | 2016 | quarter | error_014 | True | 146085 |
| 20220324000876 | 루닛 | 2021 | annual | error_014 | False | 0 |
| 20260317000111 | SK케미칼 | 2025 | annual | error_014 | False | 0 |
| 20190521000156 | 엠게임 | 2019 | quarter | error_014 | True | 202166 |
| 20150818000062 | 제이스코홀딩스 | 2015 | half | error_014 | True | 73751 |
| 20180816000065 | 알루코 | 2018 | half | error_014 | True | 204856 |
| 20170515004550 | 강동씨앤엘 | 2017 | quarter | error_014 | True | 55684 |
| 20260630001001 | 자이에스앤디 | 2025 | annual | ZIP:['xml'] | True | 871880 |
| 20180525000056 | 흥국화재 | 2018 | quarter | error_014 | False | 0 |
| 20250328001392 | 아이티센글로벌 | 2024 | annual | error_014 | False | 0 |
