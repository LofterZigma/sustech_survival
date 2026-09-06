"""Offline tests for the mirror module's pure-Python helpers.

Skips the live HTTP path (which is exercised in dev — these tests
just guard the no-network surface: URL building, code normalization,
PDF extraction with a real local file, dept listing parsing, error
classes).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# -- URL + normalization ------------------------------------------------------


def test_syllabus_url_uppercases_code():
    from sustech_survival.mirror.syllabus import syllabus_url
    assert syllabus_url("cle022") == "https://mirrors.sustech.edu.cn/courses/syllabus/CLE022.pdf"
    assert syllabus_url("  mse202  ") == "https://mirrors.sustech.edu.cn/courses/syllabus/MSE202.pdf"
    assert syllabus_url("CH103") == "https://mirrors.sustech.edu.cn/courses/syllabus/CH103.pdf"


def test_syllabus_html_url():
    from sustech_survival.mirror.syllabus import syllabus_html_url
    assert syllabus_html_url("MSE202") == (
        "https://mirrors.sustech.edu.cn/courses/syllabus/html/MSE202.html"
    )


def test_mirror_base_constant():
    from sustech_survival.mirror.syllabus import MIRROR_BASE
    assert MIRROR_BASE == "https://mirrors.sustech.edu.cn"


# -- PDF extraction (uses a real PDF if one is on disk) ----------------------


def _local_pdf() -> Path | None:
    p = Path.home() / ".sustech_survival" / "downloads" / "syllabus" / "CLE022.pdf"
    return p if p.exists() else None


def test_extract_text_returns_nonempty_for_real_pdf():
    pdf = _local_pdf()
    if pdf is None:
        pytest.skip("CLE022.pdf not in ~/.sustech_survival/downloads/syllabus/")
    from sustech_survival.mirror.syllabus import extract_text
    text = extract_text(pdf.read_bytes())
    # Real syllabus PDFs from mirrors.sustech.edu.cn should mention the
    # course code and "COURSE SPECIFICATION" marker. If this fails on a
    # new file format, the regex below is the thing to update.
    assert "CLE022" in text
    assert "COURSE SPECIFICATION" in text or "课程详述" in text


def test_extract_text_on_empty_bytes_raises_friendly():
    from sustech_survival.mirror.syllabus import extract_text, SyllabusFetchError
    with pytest.raises(SyllabusFetchError):
        extract_text(b"")


# -- Error classes -----------------------------------------------------------


def test_syllabus_error_inheritance():
    from sustech_survival.mirror.syllabus import (
        SyllabusError,
        SyllabusNotFound,
        SyllabusFetchError,
    )
    assert issubclass(SyllabusNotFound, SyllabusError)
    assert issubclass(SyllabusFetchError, SyllabusError)
    with pytest.raises(SyllabusError):
        raise SyllabusNotFound("test")
    with pytest.raises(SyllabusError):
        raise SyllabusFetchError("test")


# -- HTML directory parsing -------------------------------------------------


def test_parse_directory_hrefs_decodes_unicode():
    from sustech_survival.mirror.syllabus import _parse_directory_hrefs
    html = """
    <a href="../">Parent directory/</a>
    <a href="%E6%9D%90%E6%96%99%E7%A7%91%E5%AD%A6%E4%B8%8E%E5%B7%A5%E7%A8%8B%E7%B3%BB/">材料系/</a>
    <a href="MSE202.pdf">MSE202.pdf</a>
    <a href="?C=N&O=A">sort</a>
    """
    out = _parse_directory_hrefs(html, base="/x/", only_dirs=True)
    assert out == ["材料科学与工程系"]


def test_parse_directory_hrefs_files_when_not_only_dirs():
    from sustech_survival.mirror.syllabus import _parse_directory_hrefs
    html = '<a href="MSE202.pdf">MSE202.pdf</a>'
    out = _parse_directory_hrefs(html, base="/x/", only_dirs=False)
    assert "MSE202.pdf" in out


# -- TIS fallback: TIS rows → unified dict shape ----------------------------


def _row(**kw):
    """Build a fake TIS grade row with sensible defaults."""
    base = {
        "kcdm": "MSE202", "kcmc": "物理化学", "kcmc_en": "Physical Chemistry",
        "yxmc": "材料系", "yxmc_en": "MSE",
        "kcxz": "必修", "kcxzen": "Required",
        "kclb": "专业基础课", "kclben": "MR",
        "khfs": "考试", "khfs_en": "examination",
        "xf": 3, "zzcj": "74", "pm": "40", "zrs": "62",
        "xnxqmc": "2026春季", "xnxq": "2025-20262",
    }
    base.update(kw)
    return base


def test_from_grade_row_unified_shape():
    from sustech_survival.mirror.tis_fallback import _from_grade_row
    d = _from_grade_row(_row(), source="tis_grades")
    assert d["code"] == "MSE202"
    assert d["name"] == "物理化学"
    assert d["name_en"] == "Physical Chemistry"
    assert d["department"] == "材料系"
    assert d["credits"] == 3
    assert d["score"] == "74"
    assert d["rank"] == "40"
    assert d["class_size"] == "62"
    assert d["semester"] == "2026春季"
    assert d["source"] == "tis_grades"
    # raw row is preserved for callers that want everything
    assert d["raw"]["kcdm"] == "MSE202"


def test_from_grade_row_empty_score():
    from sustech_survival.mirror.tis_fallback import _from_grade_row
    d = _from_grade_row(_row(zzcj="", pm="", zrs=""), source="tis_grades")
    assert d["score"] == ""
    assert d["rank"] == ""
    assert d["class_size"] == ""


def test_from_catalog_row_unified_shape():
    from sustech_survival.mirror.tis_fallback import _from_catalog_row
    fake = MagicMock()
    fake.code = "BIO103"
    fake.name = "生物学原理"
    fake.credits = 3.0
    fake.teachers = ["教师A", "教师B"]
    d = _from_catalog_row(fake, source="tis_catalog")
    assert d["code"] == "BIO103"
    assert d["name"] == "生物学原理"
    assert d["credits"] == 3.0
    assert d["score"] == ""  # catalog doesn't carry scores
    assert d["source"] == "tis_catalog"


def test_fetch_course_text_renders_human_readable(monkeypatch):
    from sustech_survival.mirror.tis_fallback import _from_grade_row
    from sustech_survival.mirror.tis_fallback import fetch_course_text
    # fetch_course_text only knows about its return value, so call the
    # inner helper directly and pipe through the same formatter.
    from sustech_survival.mirror import tis_fallback as t
    # Reach into the private formatter via the public path: round-trip.
    # NOTE: monkeypatch handles teardown so this doesn't leak into other
    # tests (earlier revision used bare `t.fetch_course_json = ...` and
    # leaked).
    monkeypatch.setattr(t, "fetch_course_json",
                        MagicMock(return_value=_from_grade_row(_row(), source="tis_grades")))
    out = fetch_course_text("MSE202")
    assert "MSE202" in out
    assert "物理化学" in out
    assert "材料系" in out
    assert "Credits: 3" in out
    assert "Score: 74" in out
    assert "Source: tis_grades" in out


# -- fetch_course_json end-to-end (mocked) ----------------------------------


def test_fetch_course_json_returns_none_for_empty_code():
    from sustech_survival.mirror.tis_fallback import fetch_course_json
    assert fetch_course_json("") is None
    result = fetch_course_json(None)  # type: ignore[arg-type]
    assert result is None


def test_fetch_course_json_prefers_grades_over_catalog(monkeypatch):
    """When the user has taken the course, grades data wins over catalog."""
    from sustech_survival.mirror import tis_fallback as t

    fake_auth = MagicMock()
    fake_auth.ensure.return_value = (True, "stub")
    fake_get_courses = MagicMock(return_value=[
        _row(kcdm="MSE202"),
        _row(kcdm="BIO103", kcmc="生命科学概论"),
    ])

    # Patch the SOURCES the function imports, by name (the function does
    # `from sustech_survival.sso import TISAuth` and
    # `from sustech_survival.tis.courses import get_courses` inside).
    monkeypatch.setattr("sustech_survival.sso.TISAuth", lambda: fake_auth)
    monkeypatch.setattr("sustech_survival.tis.courses.get_courses", fake_get_courses)

    out = t.fetch_course_json("MSE202")
    assert out is not None
    assert out["source"] == "tis_grades"
    assert out["code"] == "MSE202"


def test_fetch_course_json_case_insensitive(monkeypatch):
    from sustech_survival.mirror import tis_fallback as t
    fake_auth = MagicMock(ensure=MagicMock(return_value=(True, "x")))
    monkeypatch.setattr("sustech_survival.sso.TISAuth", lambda: fake_auth)
    monkeypatch.setattr("sustech_survival.tis.courses.get_courses",
                        lambda s: [_row(kcdm="MSE202")])
    out = t.fetch_course_json("mse202")
    assert out is not None
    assert out["code"] == "MSE202"
    out2 = t.fetch_course_json("  MSE202  ")
    assert out2 is not None
    assert out2["code"] == "MSE202"


def test_fetch_course_json_returns_none_when_no_data(monkeypatch):
    """When TISAuth fails AND catalog returns nothing, return None."""
    from sustech_survival.mirror import tis_fallback as t
    fake_auth = MagicMock(ensure=MagicMock(return_value=(False, "no auth")))
    monkeypatch.setattr("sustech_survival.sso.TISAuth", lambda: fake_auth)
    assert t.fetch_course_json("DOESNOTEXIST") is None
