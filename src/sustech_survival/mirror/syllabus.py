"""
sustech_survival.mirror.syllabus — Download + parse course syllabi (教学大纲).

The mirror at ``mirrors.sustech.edu.cn/courses/syllabus/`` serves
official per-course syllabi as PDFs. This module talks to the mirror
(no auth) and provides:

  - download / fetch / open_in_browser / exists — raw PDF access
  - extract_text — best-effort PDF → plain text using pypdf

PDF text extraction is hit-or-miss:
  ✓ Most published syllabi (CLE022, CH103, MSE202, ...) have
    "课程详述 / COURSE SPECIFICATION" sections in real text and
    extract cleanly to ~5-15 KB of structured text.
  ✗ Scanned-image syllabi (rare, but exists for some older
    courses) extract to empty strings — pypdf is a text-only
    library, no OCR.

When the mirror doesn't help, fall back to live TIS endpoints
(``sustech_survival.tis.courses.get_courses`` etc.) which return
structured JSON with the same course data.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Optional, Union

import requests

from sustech_survival import _cache

__all__ = [
    "syllabus_url",
    "fetch",
    "download",
    "open_in_browser",
    "exists",
    "fetch_text",
    "extract_text",
    "list_departments",
    "MIRROR_BASE",
    "DEFAULT_KIND",
    "DEFAULT_TIMEOUT",
    "SyllabusError",
    "SyllabusNotFound",
    "SyllabusFetchError",
]

# -- Constants ---------------------------------------------------------------

#: Base URL of the SUSTech open-source mirror (sustech.online).
#: Unauthenticated — no SSO/TIS required.
MIRROR_BASE = "https://mirrors.sustech.edu.cn"

#: Path prefix for syllabus PDFs on the mirror.
SYLLABUS_PREFIX = "/courses/syllabus"

#: Path to the per-department syllabus aggregate directory.
#: Files are named ``<code>_<chinese_name>.pdf``.
AGGREGATE_PREFIX = "/courses/教学大纲汇总"

#: Default request timeout in seconds. Mirror occasionally returns
#: 5xx for slow backends; keep generous to avoid spurious timeouts.
DEFAULT_TIMEOUT = 20

#: Filesystem subdirectory under the user's config root.
DEFAULT_KIND = "syllabus"


# -- URL helpers -------------------------------------------------------------


def syllabus_url(course_code: str) -> str:
    """Mirror URL for the syllabus PDF of ``course_code`` (no HEAD check).

    Accepts lower-case / whitespace, normalizes to UPPER. e.g.:
      syllabus_url("cle022") → https://mirrors.sustech.edu.cn/courses/syllabus/CLE022.pdf
    """
    return f"{MIRROR_BASE}{SYLLABUS_PREFIX}/{_normalize_code(course_code)}.pdf"


def syllabus_html_url(course_code: str) -> str:
    """Mirror URL for the HTML rendering of the syllabus (if it exists)."""
    return f"{MIRROR_BASE}{SYLLABUS_PREFIX}/html/{_normalize_code(course_code)}.html"


def _normalize_code(course_code: str) -> str:
    """Strip whitespace + uppercase. Internal helper; no validation."""
    return (course_code or "").strip().upper()


# -- HTTP helpers ------------------------------------------------------------


def _session() -> requests.Session:
    """Plain unauthenticated session. Don't reuse SSO cookies here."""
    s = requests.Session()
    s.headers["User-Agent"] = (
        "sustech_survival/mirror (+https://github.com/dumixthestpd/sustech_survival)"
    )
    return s


def exists(course_code: str, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """HEAD-probe the mirror. True iff a PDF exists at the URL.

    Raises SyllabusFetchError for transport failures so callers can
    distinguish "no" (False) from "couldn't tell" (raises).
    """
    url = syllabus_url(course_code)
    try:
        r = _session().head(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        raise SyllabusFetchError(f"network error probing {url}: {e}") from e
    return r.status_code == 200


def fetch(course_code: str, *, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """Download syllabus PDF and return raw bytes.

    Raises:
        SyllabusNotFound: 404.
        SyllabusFetchError: other transport / 5xx.
    """
    url = syllabus_url(course_code)
    try:
        r = _session().get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        raise SyllabusFetchError(f"network error fetching {url}: {e}") from e
    if r.status_code == 404:
        raise SyllabusNotFound(
            f"no syllabus on mirror for course {course_code!r} (URL: {url}). "
            f"Course may be new, removed, or use a different code on TIS."
        )
    if r.status_code != 200:
        raise SyllabusFetchError(
            f"mirror returned {r.status_code} for {url}: {r.text[:120]!r}"
        )
    return r.content


def fetch_text(course_code: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Convenience: download + extract text in one call. Returns '' on
    scanned-image syllabi (pypdf returns empty string for those).
    """
    return extract_text(fetch(course_code, timeout=timeout))


# -- PDF → text --------------------------------------------------------------


def extract_text(pdf_bytes: bytes) -> str:
    """Extract plain text from a syllabus PDF using pypdf.

    Returns the concatenated text of every page, separated by form feeds
    (``\\f``). Empty string if the PDF is scanned/image-only — pypdf has
    no OCR. Raises SyllabusFetchError on PDF parse errors (corrupt file,
    encrypted, etc.).
    """
    try:
        import pypdf
    except ImportError as e:
        raise SyllabusFetchError(
            "pypdf is required for extract_text(); "
            "install with `pip install sustech_survival[mirror]`"
        ) from e
    try:
        import io
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            parts.append(txt)
        return "\f".join(parts)
    except Exception as e:  # pypdf raises many exception types
        raise SyllabusFetchError(f"failed to extract PDF text: {e}") from e


# -- Filesystem helpers ------------------------------------------------------


def _default_out_dir(kind: str = DEFAULT_KIND) -> Path:
    """Default download directory. Honors ``downloads_dir`` config knob
    and falls back to ``<config_root>/downloads/<kind>``. Mirrors the
    pattern used by bb/download.py.
    """
    cfg = _cache.load_config()
    d = (cfg.get("syllabus") or {}).get("downloads_dir") or cfg.get("downloads_dir")
    if d:
        return Path(d).expanduser()
    return _cache.config_root() / "downloads" / kind


def download(
    course_code: str,
    out_dir: Optional[Union[str, Path]] = None,
    *,
    overwrite: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    """Download to disk. Default target: ``<out_dir>/<CODE>.pdf``.

    Default: skip if file exists (mirror rarely changes published PDFs;
    respects user edits). Pass ``overwrite=True`` to replace.
    """
    code = _normalize_code(course_code)
    target_dir = Path(out_dir).expanduser() if out_dir else _default_out_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{code}.pdf"
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"{target} already exists; pass overwrite=True to replace it."
        )
    body = fetch(code, timeout=timeout)
    target.write_bytes(body)
    return target.resolve()


def open_in_browser(course_code: str) -> bool:
    """Open the syllabus URL in the default browser. No 404 check."""
    return webbrowser.open(syllabus_url(course_code))


# -- Aggregate / per-department directory listing ----------------------------


def list_departments(*, timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """Parse the 教学大纲汇总 directory index to find all department
    subdirectories. Each entry is the URL-encoded Chinese department name
    suitable for passing to :func:`list_aggregate_syllabi`.

    Returns an empty list on 403 / parse failure — the directory listing
    endpoint is more aggressively rate-limited than direct file fetches.
    """
    url = f"{MIRROR_BASE}{AGGREGATE_PREFIX}/"
    try:
        r = _session().get(url, timeout=timeout)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    return _parse_directory_hrefs(r.text, base=AGGREGATE_PREFIX + "/", only_dirs=True)


# Tiny HTML parser — the mirror serves Nginx auto-index pages with
# <a href="..."> entries. We don't need a full HTML parser for that.
import re as _re
_HREF_RE = _re.compile(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>')


def _parse_directory_hrefs(html: str, base: str, *, only_dirs: bool) -> list[str]:
    """Extract hrefs from an Nginx autoindex page. If ``only_dirs``,
    filter to entries that also have a matching ``title=`` attribute
    (Nginx uses ``title`` for the link text — but the directory hint
    comes from the trailing slash on the path, which we detect by
    scanning the parent <tr>).

    Returns the decoded basename (last path segment, no trailing slash).
    """
    out: list[str] = []
    for m in _HREF_RE.finditer(html):
        href, title = m.group(1), m.group(2).strip()
        if href in ("../", "/", "") or href.startswith("?"):
            continue
        if only_dirs and not href.endswith("/"):
            continue
        # Decode URL-encoded segment (e.g. %E6%9D%90%E6%96%99... → 材料系)
        from urllib.parse import unquote
        name = unquote(href.rstrip("/"))
        if name and name != "Parent directory":
            out.append(name)
    return out


# -- Errors ------------------------------------------------------------------


class SyllabusError(Exception):
    """Base class for syllabus module errors."""


class SyllabusNotFound(SyllabusError):
    """Mirror returned 404 for the requested course code."""


class SyllabusFetchError(SyllabusError):
    """Transport-level failure (timeout, connection error, 5xx, PDF parse)."""
