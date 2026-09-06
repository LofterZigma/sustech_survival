"""
sustech_survival.mirror — Access the SUSTech CRA open-source mirror.

The mirror at ``mirrors.sustech.edu.cn`` is maintained by SUSTech CRA
(Computing Resource Association) and is unauthenticated. The
``mirror/`` module is the umbrella for everything we read from it:

  - syllabus/                  (course 教学大纲 PDFs, ~all courses)
      html/                     (HTML versions of same syllabi)
      教学大纲汇总/<dept>/      (same content, organized by department)
  - 本科人才培养方案/            (per-major, per-year training plans)
  - curriculum_for_international_students/
  - site/sustech-online/documents/  (campus map, freshman handbook, ...)

Subcommand layout (sustech mirror ...):
  syllabus   — get / exists / url / open / batch / extract (PDF→text)
  program    — per-major training-plan PDFs
  handbook   — freshman + college handbooks
  map        — campus map PDF
  list       — directory listing for a subpath (parse the HTML)

Python API:
  from sustech_survival.mirror import syllabus
  text = syllabus.fetch_text("CLE022")  # PDF → str (uses pypdf)

The mirror is best-effort: some PDFs are scanned images (no extractable
text), and the directory-listing endpoint occasionally returns 403.
When the mirror can't help, fall back to live TIS endpoints
(``sustech tis grades``, ``sustech tis courses``) which return
structured JSON.
"""
from __future__ import annotations

# Re-export the syllabus sub-API at the package level so users can
# `from sustech_survival.mirror import syllabus_url` without a submodule
# import. The CLI subcommand namespacing is in cli.py.
from .syllabus import (  # noqa: F401  (re-export)
    DEFAULT_KIND as _DEFAULT_KIND,
    MIRROR_BASE,
    SYLLABUS_PREFIX,
    SyllabusError,
    SyllabusFetchError,
    SyllabusNotFound,
    download as syllabus_download,
    exists as syllabus_exists,
    extract_text as syllabus_extract_text,
    fetch as syllabus_fetch,
    open_in_browser as syllabus_open_in_browser,
    syllabus_url,
)

__all__ = [
    "MIRROR_BASE",
    "syllabus_url",
    "syllabus_fetch",
    "syllabus_exists",
    "syllabus_extract_text",
    "syllabus_download",
    "syllabus_open_in_browser",
    "SyllabusError",
    "SyllabusNotFound",
    "SyllabusFetchError",
]
