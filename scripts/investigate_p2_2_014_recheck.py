"""P2-2 quick check: does DART's document.xml API still 014 (file-not-found)
for the two P2-1 filings today, or has document.xml since become available
(handoff hypothesis 'a' -- retrying later resolves it)?

Read-only: only calls get_document_zip() to inspect the response, does not
write anything to disk or DB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.dart_client import DartClient  # noqa: E402
from collector.downloader import _parse_dart_xml_error  # noqa: E402

RCEPT_NOS = ["20260814003597", "20260811000654", "20260813001784"]

client = DartClient()
for rcept_no in RCEPT_NOS:
    zip_bytes = client.get_document_zip(rcept_no)
    if zip_bytes[:2] == b"PK":
        print(f"{rcept_no}: PK (zip returned) -- {len(zip_bytes)} bytes")
    else:
        status_code, message = _parse_dart_xml_error(zip_bytes)
        print(f"{rcept_no}: DART error [{status_code}] {message}")

print("\n--- zip contents (read-only, not written to disk) ---")
import io, zipfile
for rcept_no in RCEPT_NOS:
    zip_bytes = client.get_document_zip(rcept_no)
    if zip_bytes[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        print(f"{rcept_no}: {zf.namelist()}")
