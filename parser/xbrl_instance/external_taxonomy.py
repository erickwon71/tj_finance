"""
Shared plumbing for Phase 5-A's external-taxonomy fallback (docs/plans/
xbrl_instance_parser_todo_2026-08-05.md — 웰킵스하이텍 2019Q3, taxonomy vintage
2019-10-01). Some older DART taxonomy vintages don't bundle *anything*
standard-concept-related locally in a filer's own zip — no `<link:roleType>`
(role_map.py) and no Korean/English label for a standard `ifrs-full:`/`dart:`
concept (taxonomy_linkbase.py::resolve_external_labels) — only the filer's
own entity-specific extensions. Both live in DART's shared taxonomy package
instead, reached by following `xsd:import`/`xsd:include` chains out to
`dart.fss.or.kr`. This module is the one place that talks to the network for
that: fetch-with-cache, retry, and the two link-graph queries both callers
need (xsd import/include edges, and `<link:linkbaseRef>` edges for a given
role). Neither role_map.py nor taxonomy_linkbase.py should call `requests`
directly — go through here so there's one cache dir, one User-Agent lesson,
one retry policy.

★ dart.fss.or.kr resets the connection outright for a non-browser-looking
User-Agent (verified empirically: identical request, only the header
differed) — the header below is deliberately the exact one
collector/legacy_downloader.py already uses successfully against the same
host, not a second convention.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

import requests
from lxml import etree
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_LINK_NS = "http://www.xbrl.org/2003/linkbase"
_XLINK_NS = "http://www.w3.org/1999/xlink"

_FETCH_TIMEOUT = 15
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _cache_path(url: str) -> Path:
    import re
    from collector.config import TAXONOMY_CACHE_DIR
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", url)
    return TAXONOMY_CACHE_DIR / safe_name


@retry(
    retry=retry_if_exception_type(requests.exceptions.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    reraise=True,
)
def _get_with_retry(url: str) -> requests.Response:
    """A light retry, distinct from collector.config's API-quota-tuned
    MAX_RETRIES/RETRY_WAIT_* (5 attempts up to 120s — far too slow for a
    bounded schema-fetch BFS). DART's taxonomy host occasionally resets a
    connection under rapid sequential requests (observed empirically)."""
    resp = requests.get(url, timeout=_FETCH_TIMEOUT, headers=_HEADERS)
    resp.raise_for_status()
    return resp


def fetch(url: str) -> Path | None:
    """Fetch (or read from an on-disk cache — the same taxonomy vintage's
    shared schema/linkbase is identical for every filer that uses it, no
    need to re-download it once per filing) an external taxonomy file.
    Returns the local cache path, never raises — a network hiccup here is a
    degraded-fallback path, not a pipeline-halting error."""
    from collector.config import TAXONOMY_CACHE_DIR

    cache_file = _cache_path(url)
    if cache_file.exists():
        return cache_file
    try:
        resp = _get_with_retry(url)
        TAXONOMY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(resp.content)
        return cache_file
    except Exception as e:  # noqa: BLE001 — degrade to "not found", never crash extraction
        logger.warning(f"external_taxonomy: fetch 실패 url={url!r}: {type(e).__name__}: {e}")
        return None


def parse(url: str) -> etree._Element | None:
    """fetch() + parse. None on either failure (never raises)."""
    path = fetch(url)
    if path is None:
        return None
    try:
        return etree.parse(str(path)).getroot()
    except Exception as e:  # noqa: BLE001 — a corrupt cache entry shouldn't crash extraction
        logger.warning(f"external_taxonomy: 캐시 파일 파싱 실패({path}): {type(e).__name__}: {e}")
        return None


def import_urls(root: etree._Element, base_url: str) -> list[str]:
    """`xsd:import`/`xsd:include` schemaLocations, resolved to absolute URLs
    against `base_url`. Only absolute http(s) results are returned — a
    local/relative schemaLocation can't be a *shared* taxonomy file."""
    out: list[str] = []
    for el in list(root.findall(f"{{{_XSD_NS}}}import")) + list(root.findall(f"{{{_XSD_NS}}}include")):
        loc = el.get("schemaLocation")
        if not loc:
            continue
        resolved = urljoin(base_url, loc)
        if resolved.startswith(("http://", "https://")):
            out.append(resolved)
    return out


def local_import_urls(xsd_path: Path) -> list[str]:
    """Same as `import_urls`, but the seed for a BFS: the *local* filing's
    own `.xsd` has no URL of its own, so only its already-absolute
    (http/https) `xsd:import`/`xsd:include` targets are usable as a starting
    point (a bare relative schemaLocation on that file points to another
    local zip member, never a shared taxonomy file)."""
    root = etree.parse(str(xsd_path)).getroot()
    out: list[str] = []
    for el in list(root.findall(f"{{{_XSD_NS}}}import")) + list(root.findall(f"{{{_XSD_NS}}}include")):
        loc = el.get("schemaLocation") or ""
        if loc.startswith(("http://", "https://")):
            out.append(loc)
    return out


def linkbase_ref_urls(root: etree._Element, base_url: str, role_contains: str) -> list[str]:
    """`<link:linkbaseRef>` hrefs whose `xlink:role` contains `role_contains`
    (e.g. "labelLinkbaseRef"), resolved to absolute URLs against `base_url`.
    This is how a taxonomy's *entry point* declares which linkbase files
    belong to it — a different mechanism from `xsd:import`/`xsd:include`
    (those wire in other *schemas*, not linkbases)."""
    out: list[str] = []
    for el in root.findall(f".//{{{_LINK_NS}}}linkbaseRef"):
        role = el.get(f"{{{_XLINK_NS}}}role") or ""
        href = el.get(f"{{{_XLINK_NS}}}href")
        if role_contains in role and href:
            out.append(urljoin(base_url, href))
    return out


def dart_first(urls: list[str]) -> list[str]:
    """Sort so `dart.fss.or.kr` URLs are tried before generic `xbrl.org`/
    `w3.org` framework schemas — those never carry DART's own role/label
    definitions, trying them first just burns through the fetch budget.

    ★ Phase 2 (pdf_only_parser_phase2_design_2026-08-12 §A-4): within the
    dart.fss.or.kr tier, further prioritize by filename pattern —
    `rol_dart_`/`rol_dart-added_` (DART's own shared roleType definitions,
    role_map.py) and `dart_`/`dart-gcd_` (DART's own shared labelLinkbaseRef
    declarations, taxonomy_linkbase.py) are the files both callers are
    actually hunting for, while the ~40 other dart.fss.or.kr URLs in a
    typical vintage's import chain are individual IAS/IFRS/IFRIC/SIC
    standard schemas that are never core-classified and rarely declare any
    label linkbase of their own (verified directly against a real vintage's
    cached files, 2013-03-31: `rol_dart_2013-03-31.xsd` sits at position
    ~46-47 of 47 in raw import order — blowing past the old budget=12 before
    ever being reached; `dart_2013-03-31.xsd`/`dart-gcd_2013-03-31.xsd` are
    reached in 2-3 hops but weren't prioritized either). This sub-sort
    doesn't remove the need for a budget (a vintage's true shared-definition
    file name isn't knowable in advance for a future, unseen vintage — see
    role_map.py's caution against hardcoding vintage-specific chains), it
    just means the existing budget reaches the right file far sooner.
    ★ Ordering note: `"dart_"` as a prefix does NOT also match
    `"rol_dart_..."` or `"dart-gcd_..."` (different literal prefixes,
    underscore vs hyphen) — each pattern is checked independently, so all
    four sort into the top tier without one accidentally absorbing another."""
    _DART_OWN_PREFIXES = ("rol_dart_", "rol_dart-added_", "dart_", "dart-gcd_")

    def _priority(u: str) -> tuple[int, int]:
        if "dart.fss.or.kr" not in u:
            return (1, 0)  # generic xbrl.org/w3.org framework schema — lowest priority
        base = u.rsplit("/", 1)[-1]
        if any(base.startswith(p) for p in _DART_OWN_PREFIXES):
            return (0, 0)  # DART's own shared role/label definitions — highest priority
        return (0, 1)      # other dart.fss.or.kr file (individual IAS/IFRS/... schemas)
    return sorted(urls, key=_priority)
