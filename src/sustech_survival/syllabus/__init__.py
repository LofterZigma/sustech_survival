"""
sustech_survival.syllabus — Download SUSTech course syllabi (教学大纲) PDFs.

SUSTech publishes official course syllabi on the public
`mirrors.sustech.edu.cn` mirror under `/courses/syllabus/<CODE>.pdf`.
The mirror is unauthenticated — no SSO, no TIS session required —
which makes syllabus fetching the only thing in `sustech_survival`
that works *without* logging in.

Usage:

    from sustech_survival.syllabus import fetch, download, open_in_browser, syllabus_url

    url = syllabus_url("CLE022")                    # → mirror URL
    text = fetch("CLE022")                          # → raw PDF bytes
    path = download("CLE022")                       # → ~/.sustech_survival/downloads/syllabus/CLE022.pdf
    open_in_browser("CLE022")                       # → opens URL in default browser

The course code is the TIS `kcdm` value (e.g. "CH103", "CLE022",
"MSE001", "MA117"). TIS exposes these via ``sustech tis grades`` and
``sustech tis courses``; pass any of them straight in.

Naming: 教学大纲 / syllabus / 课程大纲 all mean the same thing — the
official per-course outline published at the start of each term.
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
    "MIRROR_BASE",
]

# -- Constants ---------------------------------------------------------------

#: Base URL of the SUSTech open-source mirror (sustech.online).
#: The mirror is unauthenticated and serves static course artifacts.
MIRROR_BASE = "https://mirrors.sustech.edu.cn"

#: Path prefix for syllabus PDFs on the mirror.
SYLLABUS_PREFIX = "/courses/syllabus"

#: Default request timeout in seconds. Syllabus PDFs are < 1 MB but the
#: mirror occasionally returns 5xx for slow backends; keep a generous
#: timeout rather than retrying on the caller's behalf.
DEFAULT_TIMEOUT = 20

#: Filesystem subdirectory under the user's config root where downloads
#: are written by default. Mirrors ``bb/download.py``'s convention.
DEFAULT_KIND = "syllabus"


# -- URL helpers -------------------------------------------------------------


def syllabus_url(course_code: str) -> str:
    """Return the mirror URL for the syllabus PDF of ``course_code``.

    Args:
        course_code: TIS course code (e.g. "CH103", "CLE022"). Whitespace
            is stripped and the result is upper-cased; lower-case input
            like "cle022" is accepted.

    Returns:
        The fully-qualified URL (no HEAD check). Call :func:`exists` first
        if you want to verify availability without downloading.

    Examples:
        >>> syllabus_url("CLE022")
        'https://mirrors.sustech.edu.cn/courses/syllabus/CLE022.pdf'
        >>> syllabus_url("  ch103 ")
        'https://mirrors.sustech.edu.cn/courses/syllabus/CH103.pdf'
    """
    code = _normalize_code(course_code)
    return f"{MIRROR_BASE}{SYLLABUS_PREFIX}/{code}.pdf"


def _normalize_code(course_code: str) -> str:
    """Strip whitespace + uppercase. Internal helper; no validation."""
    return (course_code or "").strip().upper()


# -- HTTP helpers ------------------------------------------------------------


def _session() -> requests.Session:
    """Plain unauthenticated session. We deliberately don't reuse any SSO
    session — the mirror is public and adding cookies is both unnecessary
    and a fingerprinting risk on shared networks.
    """
    s = requests.Session()
    s.headers["User-Agent"] = (
        "sustech_survival/syllabus (+https://github.com/dumixthestpd/sustech_survival)"
    )
    return s


def exists(course_code: str, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """HEAD-probe the mirror. Returns True iff a PDF exists at the URL.

    Faster than :func:`fetch` for "is it downloadable?" checks because it
    doesn't pull the body. A 404 returns False; any other error (network,
    timeout, 5xx) raises — callers that want to treat "couldn't tell" as
    "missing" should wrap in try/except.
    """
    url = syllabus_url(course_code)
    r = _session().head(url, timeout=timeout, allow_redirects=True)
    return r.status_code == 200


def fetch(course_code: str, *, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """Download the syllabus PDF and return the raw bytes.

    Args:
        course_code: TIS course code.
        timeout: HTTP timeout in seconds.

    Returns:
        Raw PDF bytes (Content-Type is not validated — callers that care
        should check ``bytes[:4] == b'%PDF'``).

    Raises:
        SyllabusNotFound: mirror returned 404 (or any non-200 < 500).
        SyllabusFetchError: network / 5xx / other transport failure.
    """
    url = syllabus_url(course_code)
    try:
        r = _session().get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        raise SyllabusFetchError(f"network error fetching {url}: {e}") from e

    if r.status_code == 404:
        raise SyllabusNotFound(
            f"no syllabus on mirror for course {course_code!r} "
            f"(URL: {url}). The course may be new, removed, or use a "
            f"different code on TIS."
        )
    if r.status_code != 200:
        raise SyllabusFetchError(
            f"mirror returned {r.status_code} for {url}: {r.text[:120]!r}"
        )
    return r.content


# -- Filesystem helpers ------------------------------------------------------


def _default_out_dir(kind: str = DEFAULT_KIND) -> Path:
    """Default download directory.

    Precedence:
      - explicit ``out_dir`` (caller)
      - ``downloads_dir`` or ``syllabus.downloads_dir`` in config.json
      - ``<config_root>/downloads/<kind>``

    Mirrors the pattern used by ``bb/download.py`` so users get a
    consistent layout regardless of which module they downloaded from.
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
    """Download the syllabus to disk and return the resulting Path.

    The destination is ``<out_dir>/<CODE>.pdf`` where ``out_dir`` defaults
    to :func:`_default_out_dir`. Existing files are NOT overwritten unless
    ``overwrite=True`` — the mirror rarely changes a published PDF, so the
    default behavior saves bandwidth and respects user edits.

    Args:
        course_code: TIS course code.
        out_dir: destination directory (default: per config_root).
        overwrite: replace an existing file at the destination.
        timeout: HTTP timeout.

    Returns:
        Absolute :class:`pathlib.Path` to the downloaded file.

    Raises:
        SyllabusNotFound, SyllabusFetchError, FileExistsError.
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


# -- Convenience -------------------------------------------------------------


def open_in_browser(course_code: str) -> bool:
    """Open the syllabus URL in the user's default browser.

    Returns True if the browser launch succeeded. Doesn't verify that the
    PDF actually exists on the mirror — the browser will show a 404 page
    if not. Use :func:`exists` first if you want to gate this.
    """
    return webbrowser.open(syllabus_url(course_code))


# -- Errors ------------------------------------------------------------------


class SyllabusError(Exception):
    """Base class for syllabus module errors."""


class SyllabusNotFound(SyllabusError):
    """Mirror returned 404 for the requested course code."""


class SyllabusFetchError(SyllabusError):
    """Transport-level failure (timeout, connection error, 5xx, ...)."""
