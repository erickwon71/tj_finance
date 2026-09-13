"""R96(2026-09-12) — `collector/downloader.py::_pick_best_file_by_size()` 회귀 테스트.

배경: DART `document.xml` ZIP 안에 xml 이 여러 개일 때(본문 + 첨부) 기존 로직은
"가장 큰 파일"을 무조건 본문으로 골랐다. 실측(양지사 20150930000130, 티로보틱스
20180402000209)에서 첨부(감사보고서, `_00760.xml`)가 본문(`{접수번호}.xml`)보다
바이트가 더 커서 첨부가 잘못 선택됐다 — report_lines 가 "본문 섹션 없음"으로 0행
처리됨(파서는 정직했다, 콜렉터가 잘못된 파일을 준 것). 실행:
    pytest tests/test_downloader_body_vs_attachment_r96.py
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.downloader import _pick_best_file_by_size  # noqa: E402


def _make_zip(files: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_attachment_bigger_than_body_still_picks_body_by_filename():
    """실측 재현: 첨부(감사보고서)가 본문보다 커도 파일명으로 본문을 정확히 고른다."""
    rcept = "20150930000130"
    zf = _make_zip({
        f"/{rcept}.xml": b"x" * 342_379,          # 본문(사업보고서) — 더 작음
        f"/{rcept}_00760.xml": b"x" * 354_948,     # 첨부(감사보고서) — 더 큼
    })
    best = _pick_best_file_by_size(zf, rcept)
    assert best.filename == f"/{rcept}.xml"


def test_no_exact_filename_match_falls_back_to_largest():
    """본문 명명 규칙(`{접수번호}.xml`)에 안 걸리면(구형/미확인 명명) 기존 동작(가장
    큰 파일) 그대로 — R6 원칙, 모르는 모양이면 확장하지 않는다."""
    rcept = "20150930000130"
    zf = _make_zip({
        "/weird_name_a.xml": b"x" * 100,
        "/weird_name_b.xml": b"x" * 200,
    })
    best = _pick_best_file_by_size(zf, rcept)
    assert best.filename == "/weird_name_b.xml"


def test_single_xml_file_unaffected():
    """xml 이 1개뿐이면(대다수 정상 케이스) 이름 판정 자체를 안 타고 그대로 선택."""
    rcept = "20151116001903"
    zf = _make_zip({f"/{rcept}.xml": b"x" * 500})
    best = _pick_best_file_by_size(zf, rcept)
    assert best.filename == f"/{rcept}.xml"


def test_body_smaller_and_no_leading_slash_still_matched():
    """ZipInfo.filename 에 선행 '/' 가 없는 경우(아카이버 차이)도 정확히 매치한다."""
    rcept = "20180402000209"
    zf = _make_zip({
        f"{rcept}.xml": b"x" * 313_936,
        f"{rcept}_00760.xml": b"x" * 503_797,
    })
    best = _pick_best_file_by_size(zf, rcept)
    assert best.filename == f"{rcept}.xml"
