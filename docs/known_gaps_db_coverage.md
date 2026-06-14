# 알려진 커버리지 갭 (std_v2 / fin2 추출)

작성: 2026-06-14. 출처: Gate A(`scripts/validate_downloads.py`) + item 4(금융업/레거시 추출) 조사.

DART 정기보고서 다운로드는 사실상 완료(파일 무결성 거의 완벽)이나, **일부 보고서는
fin2 추출이 0행**(std_v2 미적재)이다. 아래는 그 잔여 갭의 분류·원인·처리방침이다.

## 현재 잔여 (download_tasks.gate_a)

| 버킷 | 건수 | 원인 | 처리 |
|---|---:|---|---|
| **PDF-only** | 3,044 | fin2 PDF 파서 미구현(`fin2/extract/pdf.py` 없음) | 별도 대형과제(보류) |
| **pre-2010 XML (K-GAAP)** | 13,508 | 구 DART ACODE + 다른 문서트리. 핵심 추출기 재작성 필요, 회귀 위험, 저가치(pre-2011 거의 미사용) | 보류(ROI 낮음). 일부는 비교컬럼 폴백으로 자동 복구됨 |
| **2010-2014 XML** | 257 | 레거시 ACODE 혼재 + 소형사 다양 레이아웃 | 롱테일, 보류 |
| **2015+ XML** | 83 | **이질적 롱테일**(아래) | known-gap, 케이스별 후속 |
| **MISSING_FILE (FAIL)** | 3 | 디스크 소실: 동방아그로 2003H1, KD 2015 Q1·Q3 | `reset-missing` 후 재download |

총 REVIEW/EXTRACT_EMPTY = 16,892 · FAIL = 3.

## 2015+ XML 83건 정밀조사 (item 4, 2026-06-14)

원래 596건이던 2015+ 금융업/레거시 추출0 은 item 4 수정으로 **497(83%) 복원**.
잔여 83건은 **단일 원인이 아님**(2015-2023 소·중형사, 대부분 실데이터 존재):

- **본문 XML 에 재무제표 미수록** — 예: 웅진씽크빅 2020 Q3 는 XML 에 재무제표 제목이
  아예 없음(별도 첨부 또는 미수록). = 추출 문제가 아니라 **다운로드 완전성/Gate A 영역**.
- **기타 레이아웃 변형** — 소형사별 표/제목 구조 상이. 케이스별 조사 필요.
- 보고서종류 분포: annual 32 / quarter 32 / half 19.

⟹ 소형사·다원인·일부는 비추출 이슈 → **추가 ROI 낮아 known-gap**. Gate B(PRD 04)의
보고서-vs-DB 대조가 이 중 중요한 것을 자연히 표면화하면 그때 케이스별 처리.

## item 4 에서 해소된 레이아웃 (참고)

`parser/xml/section_detector.py` `_is_statement_header` + `_detect_sections_from_paragraphs`:
1. `<P>` 표제 헤더(보험·증권·지주, "연결재무상태표" 등 — TITLE 아님)
2. 다중 주석참조 컬럼 시프트(`table_extractor`)
3. interim 연간비교표·자본변동표(SCE) 오염
4. 번호접두+기간 인라인 표제("1)재무상태표(대차대조표)제33기…", 소·중형사)

## 재방문 방법

```sql
-- 잔여 추출0 (파일 OK, fact 없음)
SELECT dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
FROM download_tasks dt JOIN filings f ON f.rcept_no=dt.rcept_no
WHERE dt.gate_a_status='REVIEW' AND dt.gate_a_reason='EXTRACT_EMPTY'
  AND dt.file_type='xml' AND f.is_final=TRUE AND f.fiscal_year>=2015
  AND NOT EXISTS (SELECT 1 FROM fact_v2 v WHERE v.rcept_no=dt.rcept_no);
```

진단도구: `scripts/diag_xml_structure.py` · `diag_trackb_sections.py` ·
`diag_trackb_extract.py` · `diag_extract_empty.py`.
재추출(수정 후): `scripts/fin2_reextract_financial.py`(purge 포함).

## K-GAAP↔IFRS 시계열 단절 (TODO, 2026-06-14)

**결정(사용자 ①, as-filed)**: pre-2011 K-GAAP 연도의 std_v2 Layer 1 = **그 해 보고서가 실제
적은 K-GAAP 원본값**(Gate B 'DB=보고서 100%' 원칙 일치). 나중 IFRS 보고서의 비교컬럼
재작성값은 2008 원본엔 없어 Gate B 검증 불가 → Layer 1 에서 제외.

- 규모: fy≤2010 own-report(map_direct) **32,596행 / 1,397사**. kgaap_gap 보충 19행.
- 예: 옵트론텍 2008 별도 자산 = 71.5B(K-GAAP as-filed) ≠ 94.4B(IFRS 재작성 비교컬럼).
- golden `optrontec_2008_kgaap_equity` 를 as-filed(71.5B/29.1B)로 갱신.

**⚠ TODO — 시계열 단절 처리**: K-GAAP(≤2010)과 IFRS(2011+) 구간이 회계기준 차이로 점프할 수
있다(연결범위·재평가). 처리안 후보: ① Layer 2(비교/달력 정규화)에서 IFRS 재작성 비교컬럼값을
별도 시계열로 노출 ② 기준 전환 플래그(`accounting_basis` K-GAAP/IFRS)로 구간 표시 ③ 시각화에서
전환연도 마커. **Layer 2 설계 시 함께 다룸**(PRD 03 §5.3 calendar 레이어와 연계).
