#!/usr/bin/env python3
"""
실패한 ZIP 내용물 진단 스크립트
실행: python diag_zip.py
"""
import io
import zipfile
import sys
from dotenv import load_dotenv
load_dotenv(".env")

from collector.dart_client import DartClient

# 실패한 접수번호 샘플 (로그에서 추출)
FAILED_RCEPT_NOS = [
    ("20260213002177", "신영증권 2026Q1"),
    ("20260515002181", "삼성전자 2026Q1"),
    ("20250515001922", "삼성전자 2025Q1"),
    ("20260515002129", "삼성바이오로직스 2026Q1"),
]

client = DartClient()

for rcept_no, label in FAILED_RCEPT_NOS:
    print(f"\n{'='*60}")
    print(f"  {label}  ({rcept_no})")
    print(f"{'='*60}")
    try:
        raw = client.get_document_zip(rcept_no)
        print(f"  응답 크기: {len(raw):,} bytes")
        print(f"  첫 4바이트: {raw[:4].hex()}  ({'ZIP OK' if raw[:2]==b'PK' else 'NOT ZIP!'})")

        if raw[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                infos = zf.infolist()
                print(f"  ZIP 내 파일 수: {len(infos)}개")
                print()
                for info in sorted(infos, key=lambda i: i.file_size, reverse=True):
                    ext = info.filename.rsplit(".", 1)[-1].lower() if "." in info.filename else "?"
                    print(f"    [{ext:6s}]  {info.file_size/1024:8.1f} KB  {info.filename}")
        else:
            print(f"  ZIP이 아님 — 원본 내용:")
            print(raw[:500].decode("utf-8", errors="replace"))

    except Exception as e:
        print(f"  오류: {e}")

client.close()
print("\n진단 완료")
