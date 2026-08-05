# 핸드오프 — "XML 파싱 자체 실패" 재확인 + XBRL 원문 발견 (2026-08-05 심야, 짧은 세션)

새 세션은 이 문서 → 필요하면 `handoff_r4_2_merged_title_table_2026-08-05.md`(직전 세션) 순으로
읽으면 된다. **구현은 하나도 하지 않았다 — 조사만 했고, 다음 착수 여부는 사용자 판단 대기.**

---

## 1. 이번 세션에 한 일 (요약)

1. 직전 핸드오프(R4-2) §6 "다음 후보" 중 "XML 파싱 자체 실패 9건" 재확인을 rcept_no 단위로
   진행 — R4-2 핸드오프의 경고("특수건설·팬엔터·포시에스는 이번에 해결한 rcept_no와 다른
   건일 가능성")가 **맞았음을 확인**.
2. `probe_residual_gap_breakdown.py`에 `is_active=true` 필터를 더해 재실행 → 잔여공백
   **24 → 14건**, 그중 "XML 파싱 자체 실패"는 **9 → 6건**(특수건설·팬엔터·포시에스는 이제
   `n_loaded>0`이라 쿼리에서 아예 빠짐 — R4-2가 고친 것과 무관하게 이미 로드된 상태).
3. 6건의 `download_tasks.file_type`이 전부 `'pdf'`임을 확인 — "XML fatal error"가 아니라
   **애초에 저장된 원본이 PDF**라서 `_parse_xml_file()`이 실패하는 것이었다.
4. OpenDART API(`document.xml`)로 6건 중 4건을 직접 재요청 → 전부 **014("파일이
   존재하지 않습니다")** 확인. 여기까지는 "DART에 XML이 없다"는 결론이었다.
5. **사용자가 DART 웹뷰어에서 박셀바이오 건의 "다운로드" 버튼에 XML이 든 zip을 직접
   목격** — 위 결론이 **틀렸음**이 드러남. 재조사 결과:
   - DART는 필링마다 **두 가지 다른 원본**을 따로 제공한다.
     ① **공시서류원본 XML**(`document.xml`, DART 독자 서식 — `<TABLE>`/`<P>` 구조,
        우리 파서 `parser/xml/dart_xml_parser.py`가 읽는 바로 그 포맷) — 이 6건은
        여기서 **진짜로 014가 맞다**(DART 웹의 `/pdf/download/main.do` 다운로드 목록에도
        이 항목 자체가 없음, PDF/XBRL 두 줄만 있음).
     ② **재무제표 원문 XBRL**(`/pdf/download/ifrs.do?rcp_no=...&dcm_no=...&lang=ko`,
        표준 XBRL instance + taxonomy(schema/linkbase) zip) — **우리 다운로더가 한 번도
        시도하지 않는 별도 엔드포인트**.
   - `dcmNo`는 `collector/legacy_downloader.py::_get_view_params()`로 얻은 뒤
     `/pdf/download/main.do?rcp_no=...&dcm_no=...`를 직접 조회하면 `ifrs.do` 링크
     유무를 알 수 있다(스크립트 없이 curl로 확인, §5 참고).

## 2. 최종 확인된 사실 (6건 전수)

| rcept_no | 기업 | 회계기간 | 공시서류원본 XML(①) | XBRL 원문(②) |
|---|---|---|---|---|
| 20250828000534 | 박셀바이오 | 2024H1 | 없음(014) | **있음** — 실제 다운로드해 `.xbrl`+`.xsd`+linkbase 5종 확인, context/기간/계정 태그 정상 |
| 20191118000002 | 웰킵스하이텍 | 2019Q3 | 없음(014) | **있음** |
| 20191119000045 | 웰킵스하이텍 | 2019Q3 | 없음(014) | **있음** |
| 20191119000058 | 웰킵스하이텍 | 2019Q3 | 없음(014) | **있음** |
| 20260513000860 | 한화에어로스페이스 | 2026Q1 | 없음(014) | **있음** |
| 20181114002329 | 자비스 | 2018Q3 | 없음(014) | **없음** — PDF만 존재(2018년 구형서식, XBRL 의무화 이전 가능성) |

**결론: 6건 중 5건은 실제 구조화된 재무 데이터(XBRL)가 DART에 존재한다.** 자비스 1건만
진짜 PDF 전용(원본 자체가 그것뿐).

## 3. 왜 지금 못 채우는가 (구현 안 한 이유)

XBRL 원문(②)은 **우리 기존 파서가 읽는 포맷과 완전히 다르다**:
- `parser/xml/dart_xml_parser.py`(Track A/B)는 DART 서식 XML 안에 `<TABLE>/<TD>`로 박힌
  본문 표, 그리고 Track A는 그 안에 섞인 `<TE ACODE="ifrs-full_...">` 임베디드 태그를
  읽는다 — **DART 서식 XML 안에서만** 동작.
- 이번에 찾은 ②는 그 DART 서식과 무관한 **독립 XBRL instance 문서**(entity코드.xbrl +
  .xsd + `_def/_cal/_pre/_lab-ko/_lab-en.xml` linkbase 5종 묶음, context/segment/
  dimension 구조). 완전히 다른 파서가 필요하다(taxonomy 링크베이스 로딩·context 매칭·
  dimension 축 해석 등, DART 서식 파서보다 구조가 다르고 일반적인 XBRL 파서 작업).
- `collector/downloader.py`/`collector/legacy_downloader.py` 둘 다 `ifrs.do` 경로를
  전혀 모른다 — 다운로드 단계부터 새로 배선해야 한다.

이건 "간단한 폴백 추가"가 아니라 **새 파서 하나를 만드는 규모의 작업**이라 이번 세션에서
설계·구현 없이 조사만 하고 멈췄다(CLAUDE.md 정책: 계획 후 자동 실행 금지).

## 4. 남은 미해결 + 다음 세션 후보

1. **XBRL 원문 파서 신설 여부 결정** — 이번에 발견한 5건 외에도 같은 패턴(공시서류원본
   XML 없음 + XBRL만 있음)이 얼마나 더 있는지 모른다. 전수를 알아야 투자 대비 효과
   판단 가능. 착수 전 census 필요(활성기업 전체에서 "document.xml=014 & ifrs.do 존재"
   조합 건수 세기).
2. **자비스 1건** — XBRL도 없는 진짜 PDF 전용. `parser/pdf/dart_pdf_parser.py`(구체인
   전용)는 이미 있지만 fin2 report_lines 계층엔 PDF 경로가 없다 — 이것도 같은 아키텍처
   갭([[architecture-report-read-layer2-only]]과 연결해서 판단 필요).
3. 직전 핸드오프(R4-2) §6 나머지 항목들 그대로 남아있음(표못잡음 6건·표잡힘-적재만안됨
   1건·표제인식 소급 260건 등) — 이번 세션과 무관, 우선순위 재논의 필요.

## 5. 재현 명령

```bash
# 활성기업 한정 잔여공백 재분해 (14건, is_active 필터 반영 버전은 아직 원본 스크립트에
# 정식 반영 안 됨 — probe_residual_gap_breakdown.py 원본에 조인 추가 필요, §6 후보로 남음)
PYTHONPATH=. .venv/bin/python /private/tmp/claude-501/-Users-taejin-Project-tj-finance/06232d18-0732-4d2d-90f2-35b127ba69f5/scratchpad/probe_xml_fail_active.py
# ↑ 세션 스크래치패드라 재부팅/세션종료 시 사라질 수 있음 — 재사용하려면
#   scripts/probe_residual_gap_breakdown.py 에 `JOIN corporations c ON ... is_active=true`
#   를 정식 반영하는 편이 낫다(§4-1 다음 세션에서 같이 처리 권장).

# dcmNo 추출 + ifrs.do 존재 확인 (예시: 박셀바이오)
PYTHONPATH=. .venv/bin/python -c "
from collector.legacy_downloader import LegacyDartScraper
s = LegacyDartScraper()
print(s._get_view_params('20250828000534'))
s.close()
"
# 그 dcmNo로:
# curl "https://dart.fss.or.kr/pdf/download/main.do?rcp_no=20250828000534&dcm_no=<dcmNo>"
# 응답 HTML에 "ifrs.do" 링크가 있으면 XBRL 원문 존재.
```

## 6. 이번 세션에 만든 파일

없음(코드/DB 변경 없음, 스크래치패드에 임시 조사 스크립트 1개만 — §5 참고, 프로젝트에
정식 커밋 안 함).

---

## 7. Census 결과 (후속 세션, §4-1 답변 — 구현 없음, 조사만)

`probe_residual_gap_breakdown.py`를 `is_active=true` 필터 추가 + `last_filed` 날짜
컷오프 제거해서 재실행(스크래치패드 `probe_xml_fail_census.py`, 프로젝트 미커밋).

**결과: 이 패턴은 이미 완전히 다 찾은 것이었다 — 추가 발견 0건.**

- 활성기업 2015+ "완전 잔여공백"(`n_loaded=0`, 그 회계기간에 아무 데이터도 못 채운 필링)
  전체 = **20건**. 이 중 6건은 2026-07/08 최근 필링이라 파이프라인 미처리(진짜 공백 아님)
  → 진짜 공백 **14건**(§1-2와 정확히 일치).
- 14건을 원인 분해하면 "XML 파싱 자체 실패(file_type=pdf)" = **정확히 6건**, 나머지
  8건(구형서식 표 못잡음 4·표 분류 실패 3·표잡힘인데 적재만 안 됨 1)은 R4-2 §6과 무관한
  이미 알려진 별개 트랙.
- 즉 §2의 6건(박셀바이오·웰킵스하이텍3·자비스·한화에어로스페이스)이 **활성기업 2015+ 범위의
  전수**다. XBRL이 실제로 있는 건 그중 5건뿐(자비스 제외).
- `download_tasks.file_type='pdf'`는 활성기업 전체로 보면 2,019건(2015+)이나 있지만
  대부분 이미 다른 rcept_no(정정 등)로 데이터가 채워졌거나 재무제표와 무관한 첨부문서라서
  진짜 공백과는 무관 — 이 숫자로 규모를 오판하지 말 것.
- 참고로 2015년 이전은 활성기업 잔여공백이 83,157건이나 되지만, layer2 정제 자체가
  2015+로 범위 제한돼 있어서 나온 숫자(2차 패스 미착수, 기존에 알려진 별개 백로그)라
  이번 census와 무관.

**판단(사용자 결정, 구현 안 함):** 새 XBRL instance 파서(taxonomy linkbase 로딩·
context/dimension 매칭 등)를 만들어도 복구되는 건 최대 5건뿐 — 투자 대비 효과가 낮다고
판단해 **이번 트랙은 여기서 종료**. 재개하려면 이 문서 §2·§7을 그대로 재확인부터.

다음 세션은 R4-2 핸드오프 §6 나머지(표못잡음 6건·표잡힘-적재만안됨 1건·표제인식 소급
260건) 또는 자비스 PDF 전용 처리방침(아키텍처 갭) 중에서 사용자와 논의해 선택.
