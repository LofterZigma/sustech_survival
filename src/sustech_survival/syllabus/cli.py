"""
sustech_survival.syllabus.cli — Click group for `sustech syllabus ...`.

Subcommands:
  get <CODE>...     Download one or more syllabus PDFs (default destination).
  url <CODE>...     Print the mirror URL(s) — pipe-friendly, no network.
  open <CODE>...    Open the syllabus URL in the default browser.
  exists <CODE>...  HEAD-probe the mirror; exit 0 iff found.
  batch             Bulk-fetch syllabi for every course in your TIS history.

The mirror at ``mirrors.sustech.edu.cn`` is unauthenticated, so every
subcommand here works WITHOUT a TIS / CAS login.
"""
from __future__ import annotations

import sys
from typing import Optional

import click

from sustech_survival import _cache
from sustech_survival.syllabus import (
    DEFAULT_KIND,
    SyllabusError,
    SyllabusFetchError,
    SyllabusNotFound,
    download as syllabus_download,
    exists as syllabus_exists,
    fetch as syllabus_fetch,
    open_in_browser as syllabus_open_in_browser,
    syllabus_url,
)


@click.group(name="syllabus",
             help="Course syllabi (教学大纲) from mirrors.sustech.edu.cn — no login required.")
def syllabus_cmd() -> None:
    """Course syllabi from the SUSTech open-source mirror.

    All subcommands talk to mirrors.sustech.edu.cn directly; no SSO/TIS
    session is required. Pass TIS course codes (e.g. ``CLE022``, ``MSE001``)
    you got from ``sustech tis grades`` / ``sustech tis courses``.
    """
    pass


# -- per-course subcommands --------------------------------------------------


@syllabus_cmd.command(name="get", help="Download syllabus PDF(s) to disk.")
@click.argument("codes", nargs=-1, required=True)
@click.option("-o", "--output", "out_dir", default=None,
              help="Destination directory. Default: ~/.sustech_survival/downloads/syllabus")
@click.option("--overwrite", is_flag=True,
              help="Replace an existing file at the destination.")
@click.option("-q", "--quiet", is_flag=True, help="Suppress per-file progress output.")
def get_cmd(codes: tuple, out_dir: Optional[str], overwrite: bool, quiet: bool):
    """Download one or more syllabi.

    Examples:

      sustech syllabus get CLE022              # one course
      sustech syllabus get CLE022 CH103 MSE001 # multiple
      sustech syllabus get --output ~/Desktop CLE022
    """
    failures: list[tuple[str, str]] = []
    successes: list[str] = []
    for code in codes:
        try:
            path = syllabus_download(code, out_dir=out_dir, overwrite=overwrite)
        except FileExistsError as e:
            failures.append((code, f"exists: {e}"))
            if not quiet:
                click.secho(f"  ⏭  {code}: {e}", fg="yellow")
            continue
        except SyllabusNotFound as e:
            failures.append((code, f"not found: {e}"))
            if not quiet:
                click.secho(f"  ❌  {code}: {e}", fg="red")
            continue
        except SyllabusFetchError as e:
            failures.append((code, f"fetch error: {e}"))
            if not quiet:
                click.secho(f"  ❌  {code}: {e}", fg="red")
            continue
        successes.append(code)
        if not quiet:
            click.secho(f"  ✅ {code} → {path}", fg="green")
    if not quiet:
        click.echo(f"\n{len(successes)} downloaded, {len(failures)} failed.")
    if failures:
        # Exit non-zero so CI / scripts can detect partial failure.
        sys.exit(1)


@syllabus_cmd.command(name="url", help="Print the mirror URL(s); no network call.")
@click.argument("codes", nargs=-1, required=True)
def url_cmd(codes: tuple):
    """Pipe-friendly URL printer. Useful for xdg-open / curl / preview tools."""
    for code in codes:
        click.echo(syllabus_url(code))


@syllabus_cmd.command(name="open",
                      help="Open the syllabus URL in your default browser.")
@click.argument("codes", nargs=-1, required=True)
def open_cmd(codes: tuple):
    """Open each CODE's syllabus URL via webbrowser.open().

    No 404 check — the browser will show a 404 page if the course has no
    syllabus on the mirror. Use ``sustech syllabus exists CODE`` first
    if you want to gate this.
    """
    for code in codes:
        url = syllabus_url(code)
        if syllabus_open_in_browser(code):
            click.secho(f"  🌐 {code} → {url}", fg="cyan")
        else:
            click.secho(f"  ❌ {code}: failed to launch browser", fg="red")
            sys.exit(1)


@syllabus_cmd.command(name="exists",
                      help="Check if a syllabus exists on the mirror (HEAD probe).")
@click.argument("codes", nargs=-1, required=True)
@click.option("-q", "--quiet", is_flag=True,
              help="Don't print; just set exit code (0 = all exist, 1 = any missing).")
def exists_cmd(codes: tuple, quiet: bool):
    """Print whether each CODE has a syllabus on the mirror.

    Exit code is 0 iff every code resolves to a real PDF. Use this to
    gate ``syllabus open`` or to bulk-check before downloading.
    """
    missing = []
    for code in codes:
        try:
            ok = syllabus_exists(code)
        except SyllabusFetchError as e:
            click.secho(f"  ❌ {code}: probe failed: {e}", fg="red")
            missing.append(code)
            continue
        if ok:
            if not quiet:
                click.secho(f"  ✅ {code}", fg="green")
        else:
            if not quiet:
                click.secho(f"  ❌ {code}: 404 on mirror", fg="red")
            missing.append(code)
    if missing:
        sys.exit(1)


# -- bulk --------------------------------------------------------------------


@syllabus_cmd.command(name="batch",
                      help="Bulk-download every syllabus for a TIS grade history.")
@click.option("--semester", default=None,
              help="Restrict to one semester (e.g. '2025-2026-1' or '2025秋季'). "
                   "Default: every semester you've taken.")
@click.option("-o", "--output", "out_dir", default=None,
              help="Destination directory. Default: ~/.sustech_survival/downloads/syllabus.")
@click.option("--overwrite", is_flag=True,
              help="Replace existing files (default: skip).")
@click.option("--limit", type=int, default=None,
              help="Cap the number of syllabi fetched (useful for testing).")
@click.option("--dry-run", is_flag=True,
              help="Print which courses WOULD be fetched, but don't download.")
def batch_cmd(semester: Optional[str], out_dir: Optional[str],
              overwrite: bool, limit: Optional[int], dry_run: bool):
    """Bulk-fetch syllabi for every course in your TIS grades.

    Requires a working TIS session (``sustech tis session refresh`` first
    if you haven't logged in recently). With --dry-run, just lists the
    courses that would be fetched and exits — handy for previewing.
    """
    from sustech_survival.tis.courses import get_courses
    from sustech_survival.sso import TISAuth

    try:
        auth = TISAuth()
        ok, reason = auth.ensure()
    except Exception as e:  # noqa: BLE001
        click.secho(f"❌ TISAuth setup failed: {e}", fg="red")
        sys.exit(1)
    if not ok:
        click.secho(
            f"❌ TIS login required for --batch (mirror has no per-student "
            f"history). Run `sustech tis session refresh` first.\n   reason: {reason}",
            fg="red",
        )
        sys.exit(1)

    try:
        rows = get_courses(auth.session, semester=semester)
    except Exception as e:  # noqa: BLE001
        click.secho(f"❌ Failed to fetch your course history: {e}", fg="red")
        sys.exit(1)

    # Deduplicate course codes (a course can appear in multiple semesters).
    codes = sorted({(r.get("kcdm") or "").strip().upper() for r in rows if r.get("kcdm")})
    if not codes:
        click.secho("No courses found in your TIS history.", fg="yellow")
        return

    click.echo(f"Found {len(codes)} unique course(s)" +
               (f" in {semester!r}" if semester else "") + ".")
    if dry_run:
        for c in codes:
            click.echo(f"  would fetch  {c}  →  {syllabus_url(c)}")
        return

    if limit:
        codes = codes[:limit]
        click.echo(f"Limiting to first {limit}.")

    successes, failures = [], []
    for code in codes:
        try:
            path = syllabus_download(code, out_dir=out_dir, overwrite=overwrite)
        except FileExistsError:
            failures.append((code, "exists"))
            click.secho(f"  ⏭  {code}: already downloaded", fg="yellow")
        except SyllabusNotFound:
            failures.append((code, "404"))
            click.secho(f"  ❌ {code}: no syllabus on mirror", fg="red")
        except SyllabusFetchError as e:
            failures.append((code, str(e)))
            click.secho(f"  ❌ {code}: {e}", fg="red")
        else:
            successes.append(code)
            click.secho(f"  ✅ {code} → {path}", fg="green")

    click.echo(f"\n{len(successes)} downloaded, {len(failures)} failed.")
    if failures:
        sys.exit(1)


__all__ = ["syllabus_cmd"]
