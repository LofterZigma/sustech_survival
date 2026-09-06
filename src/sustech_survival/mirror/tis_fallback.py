"""
sustech_survival.mirror.tis_fallback — TIS-backed machine-readable course info.

When the mirror's PDF extraction fails (scanned image, missing file,
non-standard format), fall back to live TIS data:

  - the user's own grade history (``sustech_survival.tis.courses.get_courses``)
    for courses they've already taken
  - the public course catalog (``sustech_survival.selectcourse.client``)
    for any course currently offered in the active selection round

The TIS data is **more reliable** for machine-readable fields
(code, name, dept, credits, semester, score, class size) — no PDF
parsing involved. Use it as the primary source when you need those
fields; use the mirror when you need the prose syllabus (course
description, prerequisites, weekly outline, assessment breakdown).
"""
from __future__ import annotations

from typing import Optional

__all__ = [
    "fetch_course_json",
    "fetch_course_text",
]


def fetch_course_json(course_code: str) -> Optional[dict]:
    """Try TIS-backed sources for a course by code. Returns a unified
    dict (or None if the course isn't found in any TIS data).

    The TIS ``get_courses`` endpoint only returns the **current user's**
    grade history. A course you haven't taken won't show up there.
    For un-taken courses, the public course catalog endpoint is tried
    via ``SelectCourseClient.search_campus``.

    Returns a dict shaped like::

        {
          "code": "MSE202",
          "name": "物理化学",
          "name_en": "Physical Chemistry",
          "department": "材料科学与工程系",
          "department_en": "Department of Materials Science and Engineering",
          "credits": 3.0,
          "course_type": "必修",
          "course_type_en": "Required",
          "course_category": "专业基础课",
          "exam_type": "考试",
          "score": "74",          # only present if you took it
          "rank": "40",           # only present if you took it
          "class_size": "62",     # only present if you took it
          "semester": "2026春季",
          "source": "tis_grades", # or "tis_catalog"
          "raw": {...}            # full TIS response for that row
        }
    """
    from sustech_survival.sso import TISAuth

    code = (course_code or "").strip().upper()
    if not code:
        return None

    # 1) try the user's own grade history first (cheaper + no round dependency)
    try:
        auth = TISAuth()
        ok, _ = auth.ensure()
        if ok:
            from sustech_survival.tis.courses import get_courses
            rows = get_courses(auth.session)
            for r in rows:
                if (r.get("kcdm") or "").strip().upper() == code:
                    return _from_grade_row(r, source="tis_grades")
    except Exception:  # noqa: BLE001
        pass

    # 2) fall back to the public catalog (requires an open selection round)
    try:
        from sustech_survival.selectcourse import SelectCourseClient
        auth = TISAuth()
        ok, _ = auth.ensure()
        if not ok:
            return None
        # No selection round open → catalog endpoint returns 0 rows; that's fine.
        client = SelectCourseClient()
        # search_campus uses the catalog endpoint (catalog works any time, not
        # only during selection rounds). Filter by code in the response.
        rows = client.search_campus(keyword=code) or []
        for r in rows:
            if (getattr(r, "code", "") or "").upper() == code:
                return _from_catalog_row(r, source="tis_catalog")
    except Exception:  # noqa: BLE001
        pass

    return None


def _from_grade_row(r: dict, *, source: str) -> dict:
    return {
        "code": (r.get("kcdm") or "").strip(),
        "name": r.get("kcmc") or "",
        "name_en": r.get("kcmc_en") or "",
        "department": r.get("yxmc") or "",
        "department_en": r.get("yxmc_en") or "",
        "credits": r.get("xf"),
        "course_type": r.get("kcxz") or "",
        "course_type_en": r.get("kcxzen") or "",
        "course_category": r.get("kclb") or "",
        "course_category_en": r.get("kclben") or "",
        "exam_type": r.get("khfs") or "",
        "exam_type_en": r.get("khfs_en") or "",
        "score": r.get("zzcj") or "",
        "rank": r.get("pm") or "",
        "class_size": r.get("zrs") or "",
        "semester": r.get("xnxqmc") or "",
        "source": source,
        "raw": r,
    }


def _from_catalog_row(r, *, source: str) -> dict:
    return {
        "code": getattr(r, "code", ""),
        "name": getattr(r, "name", ""),
        "name_en": "",
        "department": "",
        "department_en": "",
        "credits": getattr(r, "credits", None),
        "course_type": "",
        "course_type_en": "",
        "course_category": "",
        "course_category_en": "",
        "exam_type": "",
        "exam_type_en": "",
        "score": "",
        "rank": "",
        "class_size": "",
        "semester": "",
        "source": source,
        "raw": {"code": getattr(r, "code", ""), "name": getattr(r, "name", ""),
                "credits": getattr(r, "credits", None),
                "teachers": getattr(r, "teachers", [])},
    }


def fetch_course_text(course_code: str) -> str:
    """Convenience: render the TIS dict as human-readable text.

    The TIS data doesn't include the prose syllabus (course description,
    prereqs, weekly outline) — for that, use :func:`sustech_survival.mirror.syllabus.fetch_text`.
    This returns what's available: name, code, dept, credits, type.
    """
    d = fetch_course_json(course_code)
    if not d:
        return ""
    lines = [
        f"Course: {d['code']} {d['name']}",
    ]
    if d.get("name_en"):
        lines.append(f"  English: {d['name_en']}")
    if d.get("department"):
        lines.append(f"  Department: {d['department']}")
    if d.get("credits") is not None:
        lines.append(f"  Credits: {d['credits']}")
    if d.get("course_type"):
        lines.append(f"  Type: {d['course_type']}")
    if d.get("course_category"):
        lines.append(f"  Category: {d['course_category']}")
    if d.get("semester"):
        lines.append(f"  Semester: {d['semester']}")
    if d.get("score"):
        lines.append(f"  Score: {d['score']} (rank {d.get('rank', '?')}/{d.get('class_size', '?')})")
    lines.append(f"  Source: {d['source']}")
    return "\n".join(lines)
