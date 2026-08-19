"""P2-2 follow-up: sample check of 12 random 08-14 xbrl_zip-only filings —
does document.xml resolve normally today (08-19), or do some stay [014]
permanently? Read-only, does not save/write anything.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.dart_client import DartClient  # noqa: E402
from collector.downloader import _parse_dart_xml_error  # noqa: E402

RCEPT_NOS = [
    "20260814002693", "20260814003257", "20260814002032", "20260814001915",
    "20260814004181", "20260814001267", "20260814004160", "20260814003616",
    "20260814003472", "20260814001557", "20260814002213", "20260814003631",
]

client = DartClient()
ok, still_014 = 0, 0
for rcept_no in RCEPT_NOS:
    zip_bytes = client.get_document_zip(rcept_no)
    if zip_bytes[:2] == b"PK":
        print(f"{rcept_no}: OK (document.xml 회수됨)")
        ok += 1
    else:
        status_code, message = _parse_dart_xml_error(zip_bytes)
        print(f"{rcept_no}: [{status_code}] {message}")
        if status_code == "014":
            still_014 += 1
print(f"\n총 {len(RCEPT_NOS)}건 중 회수 {ok} / 여전히 014 {still_014}")
