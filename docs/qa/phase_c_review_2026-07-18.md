# Phase C 패턴루프 다이제스트 — 2026-07-18

> 계획=docs/plans/loop-vivid-bubble.md §D4. **패턴 단위로 판정**(값 하나씩 아님).
> 진행: 대상 79,010 중 done **403** · std_v2 version=2 **1,810행**.

## A. held 대상 — 재파싱했으나 fact 0 (본문/단위 보류)

총 **27건**. 원인 패턴별:

### 본문없음(별첨FS 추정) — 18건
- 강원에너지(00100601) 2020FY — [20210323000544](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210323000544)
- 강원에너지(00100601) 2019FY — [20200320001186](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20200320001186)
- DB손해보험(00159102) 2022Q1 — [20220516001390](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220516001390)
- DB손해보험(00159102) 2021FY — [20220317000925](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220317000925)
- DB손해보험(00159102) 2021H1 — [20210817001369](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210817001369)
- DB손해보험(00159102) 2021Q1 — [20210517001202](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210517001202)
- DB손해보험(00159102) 2021Q3 — [20211115001050](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20211115001050)
- DB손해보험(00159102) 2020FY — [20210318001164](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210318001164)
- … 외 10건

### 기타(값충돌 등) — 9건
- 강원에너지(00100601) 2023Q3 — [20231114002367](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20231114002367)
- 케이씨피드(00101752) 2023Q3 — [20231114001405](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20231114001405)
- DB손해보험(00159102) 2022FY — [20230316001440](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230316001440)
- DB손해보험(00159102) 2022H1 — [20220816001351](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220816001351)
- DB손해보험(00159102) 2022Q3 — [20221114002224](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20221114002224)
- DB손해보험(00159102) 2017H1 — [20170814001958](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20170814001958)
- DB손해보험(00159102) 2017Q1 — [20170515001808](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20170515001808)
- DB손해보험(00159102) 2017Q3 — [20171114002652](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20171114002652)
- … 외 1건

## B. 값 충돌 보류 — 후보 다중으로 canonical 미확정 (max-abs 폐지의 짝)

충돌 canonical **12종** / 영향 std_v2 행 **921개**. 빈도순:

### `is.finance_cost` — 78행
- 경방(00101628) 2015FY/consolidated — 후보[3272290889, 13628201388] [20160330001223](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20160330001223)
- 경방(00101628) 2015FY/separate — 후보[3204222374, 12466594329] [20160330001223](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20160330001223)
- 경방(00101628) 2015H1/consolidated — 후보[451683672, 7224369055] [20150817001163](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150817001163)
- 경방(00101628) 2015H1/separate — 후보[719206600, 6817144050] [20150817001163](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150817001163)
- 경방(00101628) 2015Q1/consolidated — 후보[193184225, 3619686454] [20150515001125](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150515001125)
- 경방(00101628) 2015Q1/separate — 후보[288022388, 3527407993] [20150515001125](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150515001125)
- 경방(00101628) 2015Q3/consolidated — 후보[2243245840, 10668220996] [20151116001055](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20151116001055)
- 경방(00101628) 2015Q3/separate — 후보[2215237665, 9884577453] [20151116001055](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20151116001055)

### `bs.retained_earnings` — 58행
- 경방(00101628) 2017FY/consolidated — 후보[16695395839, 687960919646] [20180330002127](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20180330002127)
- 경방(00101628) 2017FY/separate — 후보[26266923393, 697532447200] [20180330002127](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20180330002127)
- 경방(00101628) 2017Q3/consolidated — 후보[12098135200, 683363659007] [20171114000673](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20171114000673)
- 경방(00101628) 2017Q3/separate — 후보[21359103650, 692624627457] [20171114000673](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20171114000673)
- 경방(00101628) 2018FY/consolidated — 후보[11454245353, 703219769160] [20190401001920](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20190401001920)
- 경방(00101628) 2018FY/separate — 후보[30030426349, 721795950156] [20190401001920](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20190401001920)
- 경방(00101628) 2018H1/consolidated — 후보[2812465517, 694577989324] [20180814000645](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20180814000645)
- 경방(00101628) 2018H1/separate — 후보[15200963250, 706966487057] [20180814000645](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20180814000645)

### `cf.dividends_paid` — 16행
- 강남제비스코(00100939) 2025Q1/consolidated — 후보[-3798482500, 0] [20250515001493](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250515001493)
- 강남제비스코(00100939) 2026Q1/consolidated — 후보[-3798482500, 0] [20260515001676](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260515001676)
- KG케미칼(00101220) 2025FY/consolidated — 후보[-35744754620, -23349963555] [20260323001613](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260323001613)
- 경동나비엔(00101488) 2025H1/consolidated — 후보[-9394405800, 9394405773] [20250814004234](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814004234)
- 경방(00101628) 2024FY/consolidated — 후보[-3114408750, -3110269435] [20250320001362](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001362)
- 경방(00101628) 2024FY/separate — 후보[-3114408750, -3110269435] [20250320001362](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001362)
- 경방(00101628) 2025FY/consolidated — 후보[-3737290500, -3732323460] [20260318000486](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260318000486)
- 경방(00101628) 2025FY/separate — 후보[-3737290500, -3732323460] [20260318000486](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260318000486)

### `bs.trade_receivables` — 13행
- 에이프로젠바이오로직스(00101044) 2025FY/consolidated — 후보[15788866326, 47930128805] [20260320000881](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260320000881)
- KG케미칼(00101220) 2024FY/consolidated — 후보[106405979360, 819169977480] [20250320001653](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001653)
- KG케미칼(00101220) 2025H1/consolidated — 후보[102528487445, 871123856845] [20250814004455](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814004455)
- KG케미칼(00101220) 2025Q1/consolidated — 후보[103450641895, 858760209446] [20250515003005](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250515003005)
- KG케미칼(00101220) 2025Q3/consolidated — 후보[77630917457, 911481740159] [20251114003082](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20251114003082)
- 경동제약(00101549) 2024FY/consolidated — 후보[1525853390, 22932445653] [20250320001428](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001428)
- 경동제약(00101549) 2024FY/separate — 후보[1340218081, 22137886749] [20250320001428](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001428)
- 경동제약(00101549) 2025H1/consolidated — 후보[1567883242, 14290174827] [20250814003567](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814003567)

### `cf.capex` — 12행
- 케이씨피드(00101752) 2015H1/consolidated — 후보[-69442548, -44000000, -43356724, -14362399] [20150813000507](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150813000507)
- 케이씨피드(00101752) 2015H1/separate — 후보[-44000000, -43356724, -1374545, -1272727] [20150813000507](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150813000507)
- 케이씨피드(00101752) 2015Q1/consolidated — 후보[-18666693, -7949600, -5555000, -3023354] [20150514004483](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150514004483)
- 케이씨피드(00101752) 2015Q1/separate — 후보[-7949600, 0, 0, 0] [20150514004483](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150514004483)
- 케이씨피드(00101752) 2015Q3/consolidated — 후보[-132147080, -129802412, -122223398, -40169980] [20151113000614](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20151113000614)
- 케이씨피드(00101752) 2015Q3/separate — 후보[-58721832, -52200000, -22433345, -14385636] [20151113000614](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20151113000614)
- 케이씨피드(00101752) 2017Q3/consolidated — 후보[-108000000, -80200000, -61243340, -16601900] [20171114001880](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20171114001880)
- 케이씨피드(00101752) 2017Q3/separate — 후보[-108000000, -80200000, -47345200, -16601900] [20171114001880](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20171114001880)

### `is.interest_revenue` — 12행
- DB손해보험(00159102) 2024FY/consolidated — 후보[1947601870952, 2005785255390] [20250313001342](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250313001342)
- DB손해보험(00159102) 2024FY/separate — 후보[1362421951422, 1382877538496] [20250313001342](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250313001342)
- DB손해보험(00159102) 2025FY/consolidated — 후보[2122489000000, 2183195000000] [20260312001222](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260312001222)
- DB손해보험(00159102) 2025FY/separate — 후보[1507003000000, 1531547000000] [20260312001222](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260312001222)
- DB손해보험(00159102) 2025H1/consolidated — 후보[1045877000000, 1078110000000] [20250814004289](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814004289)
- DB손해보험(00159102) 2025H1/separate — 후보[748572000000, 757207000000] [20250814004289](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814004289)
- DB손해보험(00159102) 2025Q1/consolidated — 후보[520852624594, 520852624594, 534838121581, 534838121581] [20250515002214](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250515002214)
- DB손해보험(00159102) 2025Q1/separate — 후보[374586370779, 374586370779, 379046335405, 379046335405] [20250515002214](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250515002214)

### `bs.trade_payables` — 8행
- 경동제약(00101549) 2024FY/consolidated — 후보[5018188191, 23563530060] [20250320001428](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001428)
- 경동제약(00101549) 2024FY/separate — 후보[5018188191, 23454313297] [20250320001428](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001428)
- 경동제약(00101549) 2025H1/consolidated — 후보[5248836975, 22682364591] [20250814003567](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814003567)
- 경동제약(00101549) 2025H1/separate — 후보[5248836975, 22623348305] [20250814003567](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814003567)
- 경동제약(00101549) 2025Q1/consolidated — 후보[5754701361, 29361264829] [20250514000905](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250514000905)
- 경동제약(00101549) 2025Q1/separate — 후보[5795300601, 29294409596] [20250514000905](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250514000905)
- 경동제약(00101549) 2025Q3/consolidated — 후보[828632734, 23585272695] [20251114001036](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20251114001036)
- 경동제약(00101549) 2025Q3/separate — 후보[828632734, 23587435600] [20251114001036](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20251114001036)

### `bs.short_term_debt` — 6행
- KG케미칼(00101220) 2023FY/consolidated — 후보[49583330000, 528923547596] [20240321001911](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240321001911)
- KG케미칼(00101220) 2023H1/consolidated — 후보[40000000000, 561574093553] [20230814003018](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230814003018)
- KG케미칼(00101220) 2023Q3/consolidated — 후보[40000000000, 575746369190] [20231114002976](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20231114002976)
- KG케미칼(00101220) 2024H1/consolidated — 후보[89605816188, 778612579505] [20240814004435](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240814004435)
- KG케미칼(00101220) 2024Q1/consolidated — 후보[63083320000, 572580632229] [20240516002288](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240516002288)
- KG케미칼(00101220) 2024Q3/consolidated — 후보[84234493523, 688836404331] [20241114002985](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20241114002985)

### `bs.current_bonds` — 4행
- KG케미칼(00101220) 2024FY/consolidated — 후보[54168541132, 165370296234] [20250320001653](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001653)
- KG케미칼(00101220) 2025H1/consolidated — 후보[5964116993, 122725527386] [20250814004455](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814004455)
- KG케미칼(00101220) 2025Q1/consolidated — 후보[40341369855, 166046974428] [20250515003005](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250515003005)
- KG케미칼(00101220) 2025Q3/consolidated — 후보[4677263747, 128519823910] [20251114003082](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20251114003082)

### `note.depreciation` — 3행
- 경농(00101433) 2025H1/consolidated — 후보[2631659000, 5099433864] [20250814004266](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814004266)
- 경농(00101433) 2025Q3/consolidated — 후보[2611276000, 7710710352] [20251114001196](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20251114001196)
- 경방(00101628) 2026Q1/consolidated — 후보[8187692659, 8228017000] [20260515000613](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260515000613)

### `note.amortization` — 2행
- 경농(00101433) 2025H1/consolidated — 후보[12196000, 24950287] [20250814004266](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814004266)
- 경농(00101433) 2025Q3/consolidated — 후보[10721000, 35671463] [20251114001196](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20251114001196)

### `cf.investing` — 1행
- 강원에너지(00100601) 2015H1/separate — 후보[1726537249, 4168079361] [20150817000816](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20150817000816)

## C. note 추출층 결측 — D&A/R&D 파서 개선 대상

### D&A(da_total) 결측 — 8건 (FY·연결·영업이익 존재 행 기준)
- 강원에너지(00100601) 2024FY — [20250320001312](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001312)
- 강원에너지(00100601) 2023FY — [20240321000872](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240321000872)
- 강원에너지(00100601) 2022FY — [20230323001407](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230323001407)
- 강원에너지(00100601) 2021FY — [20230323001407](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230323001407)
- DB손해보험(00159102) 2024FY — [20250313001342](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250313001342)
- DB손해보험(00159102) 2023FY — [20240314001788](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314001788)
- DB손해보험(00159102) 2022FY — [20240314001788](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314001788)
- DB손해보험(00159102) 2021FY — [20240314001788](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314001788)

### R&D(rd_expense) 결측 — 68건 (FY·연결·영업이익 존재 행 기준)
- 강원에너지(00100601) 2025FY — [20260320000921](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260320000921)
- 강원에너지(00100601) 2024FY — [20250320001312](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250320001312)
- 강원에너지(00100601) 2023FY — [20240321000872](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240321000872)
- 강원에너지(00100601) 2022FY — [20230323001407](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230323001407)
- 강원에너지(00100601) 2021FY — [20230323001407](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20230323001407)
- 강원에너지(00100601) 2020FY — [20210402002033](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20210402002033)
- 강원에너지(00100601) 2019FY — [20200406002635](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20200406002635)
- 강원에너지(00100601) 2018FY — [20190401004229](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20190401004229)
- … 외 60건
