#!/usr/bin/env python3
"""DART 웹 뷰어 응답 진단 — dcmNo 추출 실패 원인 파악"""
import re, time, sys
import httpx
from lxml import html as lxml_html

DART_WEB = "https://dart.fss.or.kr"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": DART_WEB,
}

TARGETS = [
    ("20060822000056", "삼성전자 2006H1"),
    ("20001114000729", "삼성전자 2000Q3"),
    ("20200629000494", "신영증권 2019FY"),
    ("20140526000351", "제주은행 2014Q1"),
]

client = httpx.Client(timeout=15, follow_redirects=True, headers=HEADERS)

for rcept_no, label in TARGETS:
    print(f"\n{'='*65}")
    print(f"  {label}  ({rcept_no})")
    print(f"{'='*65}")

    url = f"{DART_WEB}/dsaf001/main.do"
    try:
        resp = client.get(url, params={"rcpNo": rcept_no})
        print(f"  HTTP {resp.status_code}  최종 URL: {resp.url}")
        print(f"  Content-Type: {resp.headers.get('content-type','?')}")
        print(f"  응답 크기: {len(resp.text):,} chars")

        text = resp.text

        # dcmNo 포함 여부 전수 탐색
        all_dcm = re.findall(r"dcmNo[=:\"' ]+(\d{4,})", text, re.IGNORECASE)
        print(f"\n  dcmNo 후보: {list(set(all_dcm))[:10]}")

        # viewDoc 패턴
        vd = re.findall(r"viewDoc[^)]{0,100}", text)
        print(f"  viewDoc 패턴: {vd[:3]}")

        # frame/iframe src 확인
        try:
            tree = lxml_html.fromstring(text.encode())
            frames = [(e.tag, e.get("src","")[:120]) for e in tree.iter("frame","iframe")]
            print(f"  frames: {frames[:5]}")
        except Exception as e:
            print(f"  lxml 오류: {e}")

        # 처음 800자 출력
        print(f"\n  --- 응답 앞부분 (800자) ---")
        print(text[:800].replace("\n", " ").replace("\r", ""))

    except Exception as e:
        print(f"  오류: {e}")

    time.sleep(2)

client.close()
print("\n진단 완료")
