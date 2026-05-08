#!/usr/bin/env python3
"""
validate_obj_refs.py - Reference integrity checker for OBJ bundles.

Programmatically performs the four reference-integrity checks from Step 3
of the OBJ validation workflow:

  1. Face indices (f) fall within the range of v / vt / vn counts.
     Index 0 is invalid (OBJ indices are 1-based) and is reported.
  2. Every mtllib reference in the OBJ points to an existing file.
  3. Every usemtl in the OBJ is defined as newmtl in an MTL.
  4. Every map_* in the MTL points to an existing texture file.

Public API for embedding (used by the Tkinter GUI):

  from validate_obj_refs import (
      validate_obj_path, format_result_lines, write_csv_report,
      write_text_report, ValidationResult,
  )
  result = validate_obj_path(Path("model.obj"))
  if result.overall_ok: ...

  # Optional progress callback for long-running parses:
  result = validate_obj_path(
      Path("model.obj"),
      progress_callback=lambda msg: print(msg),
  )

Usage (CLI):

    python validate_obj_refs.py /path/to/MODEL.obj
    python validate_obj_refs.py --help

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
    2 - usage or I/O error (missing argument, file not found, ...)

Notes:
  - Files are opened with utf-8-sig so a leading BOM is stripped.
  - Texture and .mtl paths are resolved relative to the directory of
    the .obj file.
  - Negative (relative) indices in faces are recognised but not
    validated; they are rare in modern exports.
  - usemtl/newmtl matching is strict literal: "name" (with quotes) is
    a different string from name. This mirrors MeshLab and other
    standard parsers; the OBJ spec does not define quote stripping.
  - Filename case sensitivity follows the filesystem (case-sensitive
    on Linux/macOS, case-insensitive on Windows).

Part of the 3D Preservation Research toolkit. See README.md in this
directory for context, installation instructions and example output.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# Texture-related MTL directives. Lowercased here; matching is
# case-insensitive against the directive token on each line.
TEXTURE_DIRECTIVES = {
    "map_kd", "map_ka", "map_ks", "map_ns", "map_d",
    "map_bump", "bump", "norm", "disp", "decal",
    "map_pr", "map_pm", "map_ps", "map_ke",
}

# Allowed character set for material names. The strict OBJ/MTL spec
# reading is "alphanumeric, underscores may be used" (no other chars).
# We extend this with two characters that are technically outside the
# spec but ubiquitous in real exports:
#   - hyphen ('-'): common in human-readable names (e.g. wood-grain).
#   - dot ('.'):    common in Blender auto-numbering (e.g. Material.001).
# Anything outside this extended set in a usemtl or newmtl name is
# flagged as spec violation: catches quotes, brackets, parentheses,
# slashes, plus signs, embedded whitespace, and other punctuation.
ALLOWED_NAME_CHARS = re.compile(r"^[A-Za-z0-9_.\-]+$")

# Cap on the number of face-index errors stored for display, to bound
# memory on heavily corrupt input. The total error count is tracked
# separately and reported in the summary even if storage is capped.
MAX_FACE_ERRORS_TRACKED = 1000

# Emit a progress callback every N OBJ lines processed during parsing.
# Tuned so that a 1.6 GB OBJ produces a handful of pings rather than a
# single 20 s silence.
OBJ_PROGRESS_INTERVAL = 5_000_000


@dataclass
class ObjData:
    """Collected data from parsing a single OBJ file."""

    v_count: int = 0
    vt_count: int = 0
    vn_count: int = 0
    mtllibs: list[str] = field(default_factory=list)
    usemtls: list[str] = field(default_factory=list)
    # Each error is (lineno, axis, index_used, count_available).
    # The list is capped at MAX_FACE_ERRORS_TRACKED entries; the true
    # total is in face_idx_errors_total.
    face_idx_errors: list[tuple[int, str, int, int]] = field(default_factory=list)
    face_idx_errors_total: int = 0
    # usemtl lines that violate the spec character rules: either
    # multiple tokens (embedded space) or a single token with chars
    # outside [A-Za-z0-9_]. Each entry is (lineno, full_name, reason).
    suspicious_usemtls: list[tuple[int, str, str]] = field(default_factory=list)


@dataclass
class MtlData:
    """Collected data from parsing a single MTL file."""

    newmtls: list[str] = field(default_factory=list)
    # Each entry is (lineno, directive_token_as_written, filename).
    maps: list[tuple[int, str, str]] = field(default_factory=list)
    # newmtl lines that violate the spec character rules; same shape
    # as suspicious_usemtls above. Each entry is (lineno, full_name, reason).
    suspicious_newmtls: list[tuple[int, str, str]] = field(default_factory=list)


@dataclass
class CheckResult:
    """Outcome of a single reference-integrity check."""

    label: str
    ok: bool
    detail: str = ""
    sub_items: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Aggregated outcome of all reference-integrity checks for one OBJ."""

    obj_path: Path
    base_dir: Path
    v_count: int
    vt_count: int
    vn_count: int
    mtllib_count: int
    usemtl_unique_count: int
    checks: list[CheckResult]
    error_count: int

    @property
    def overall_ok(self) -> bool:
        return self.error_count == 0


# --- parsing -------------------------------------------------------------


def parse_obj(
    path: Path,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> ObjData:
    """Parse an OBJ file; collect counts, references, and face-index errors.

    Uses utf-8-sig to strip a possible UTF-8 BOM on the first line.
    Optionally calls progress_callback every OBJ_PROGRESS_INTERVAL lines.
    """
    data = ObjData()
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            head = parts[0].lower()
            if head == "v":
                data.v_count += 1
            elif head == "vt":
                data.vt_count += 1
            elif head == "vn":
                data.vn_count += 1
            elif head == "f":
                _check_face(parts[1:], lineno, data)
            elif head == "mtllib":
                data.mtllibs.extend(parts[1:])
            elif head == "usemtl" and len(parts) > 1:
                name = parts[1]
                data.usemtls.append(name)
                violation = _name_spec_violation(parts[1:])
                if violation is not None:
                    full, reason = violation
                    data.suspicious_usemtls.append((lineno, full, reason))
            if (
                progress_callback is not None
                and lineno % OBJ_PROGRESS_INTERVAL == 0
            ):
                progress_callback(f"  parsed {lineno:,} lines...")
    return data


def _check_face(verts: list[str], lineno: int, data: ObjData) -> None:
    """Validate each vertex-reference in a face line.

    Index 0 is invalid (OBJ uses 1-based indexing) and reported.
    Negative (relative) indices are recognised but not validated.
    """
    for vert in verts:
        idxs = vert.split("/")
        v_idx = _safe_int(idxs[0]) if len(idxs) >= 1 else None
        vt_idx = _safe_int(idxs[1]) if len(idxs) >= 2 and idxs[1] else None
        vn_idx = _safe_int(idxs[2]) if len(idxs) >= 3 and idxs[2] else None
        _record_face_error_if_invalid(v_idx, "v", data.v_count, lineno, data)
        _record_face_error_if_invalid(vt_idx, "vt", data.vt_count, lineno, data)
        _record_face_error_if_invalid(vn_idx, "vn", data.vn_count, lineno, data)


def _record_face_error_if_invalid(
    idx: Optional[int],
    axis: str,
    count: int,
    lineno: int,
    data: ObjData,
) -> None:
    """Append a face-index error if idx is invalid (zero or out of range).

    Caps stored entries at MAX_FACE_ERRORS_TRACKED but always increments
    the total counter. Skips negative (relative) indices entirely.
    """
    if idx is None or idx < 0:
        return
    if idx == 0 or idx > count:
        data.face_idx_errors_total += 1
        if len(data.face_idx_errors) < MAX_FACE_ERRORS_TRACKED:
            data.face_idx_errors.append((lineno, axis, idx, count))


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _name_spec_violation(name_tokens: list[str]) -> Optional[tuple[str, str]]:
    """Check whether a usemtl/newmtl name violates the spec character rules.

    Returns (full_attempted_name, reason) if a violation is detected,
    else None. Reasons:
      - "embedded space": multiple tokens after the directive (spec
        disallows blanks in names).
      - "non-alphanumeric": a single token containing characters
        outside the allowed set [A-Za-z0-9_.-]. Catches quotes,
        brackets, parentheses, slashes, etc.
    """
    if len(name_tokens) > 1:
        return (" ".join(name_tokens), "embedded space")
    name = name_tokens[0]
    if not ALLOWED_NAME_CHARS.match(name):
        return (name, "non-alphanumeric")
    return None


def parse_mtl(path: Path) -> MtlData:
    """Parse an MTL file; collect material names and texture references.

    Uses utf-8-sig to strip a possible UTF-8 BOM on the first line.
    """
    data = MtlData()
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            head = parts[0].lower()
            if head == "newmtl" and len(parts) > 1:
                data.newmtls.append(parts[1])
                violation = _name_spec_violation(parts[1:])
                if violation is not None:
                    full, reason = violation
                    data.suspicious_newmtls.append((lineno, full, reason))
            elif head in TEXTURE_DIRECTIVES and len(parts) > 1:
                # Texture directives may carry flag arguments (-s, -o,
                # -mm, ...) before the filename. Convention: filename
                # is the last token on the line.
                fname = parts[-1]
                data.maps.append((lineno, parts[0], fname))
    return data


# --- main entry point ----------------------------------------------------


def validate_obj_path(
    obj_path: Path,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> ValidationResult:
    """Run all four reference-integrity checks on a single OBJ file.

    Returns a ValidationResult with structured per-check outcomes,
    suitable for both CLI display and programmatic use (e.g. GUI).

    Raises FileNotFoundError if the OBJ file does not exist.

    progress_callback, if provided, is called with short status strings
    at major stages and periodically during long parses. Useful for
    streaming output to a GUI log so large files do not appear stuck.
    """
    obj_path = obj_path.expanduser().resolve()
    if not obj_path.is_file():
        raise FileNotFoundError(f"OBJ file not found: {obj_path}")

    base_dir = obj_path.parent

    def _progress(msg: str) -> None:
        if progress_callback is not None:
            progress_callback(msg)

    _progress("reading OBJ...")
    obj = parse_obj(obj_path, progress_callback=progress_callback)
    _progress(
        f"OBJ parsed: v={obj.v_count} vt={obj.vt_count} "
        f"vn={obj.vn_count} mtllib={len(obj.mtllibs)} "
        f"usemtl(unique)={len(set(obj.usemtls))}"
    )

    checks: list[CheckResult] = []
    errors = 0

    # Check 1 - face indices
    if obj.face_idx_errors_total:
        errors += 1
        sub: list[str] = [_render_face_error(e) for e in obj.face_idx_errors[:5]]
        if obj.face_idx_errors_total > 5:
            sub.append(f"... (+{obj.face_idx_errors_total - 5} more)")
        checks.append(CheckResult(
            label=(
                f"Face indices: {obj.face_idx_errors_total} "
                f"out-of-range references"
            ),
            ok=False,
            sub_items=sub,
        ))
    else:
        checks.append(CheckResult(label="All face indices within range", ok=True))

    # Check 2 - mtllib files exist
    mtl_data: dict[str, MtlData] = {}
    for mtl_name in obj.mtllibs:
        mtl_path = (base_dir / mtl_name).resolve()
        if not mtl_path.is_file():
            errors += 1
            checks.append(CheckResult(
                label="MTL file not found", ok=False, detail=mtl_name,
            ))
        else:
            checks.append(CheckResult(
                label="MTL file present", ok=True, detail=mtl_name,
            ))
            _progress(f"checking MTL: {mtl_name}")
            mtl_data[mtl_name] = parse_mtl(mtl_path)

    # Check 3 - usemtl matches newmtl
    all_newmtls: set[str] = set()
    for d in mtl_data.values():
        all_newmtls.update(d.newmtls)
    usemtls = set(obj.usemtls)
    missing = usemtls - all_newmtls
    if missing:
        errors += 1
        checks.append(CheckResult(
            label=f"usemtl without matching newmtl: {len(missing)}",
            ok=False,
            sub_items=sorted(missing),
        ))
    elif usemtls:
        checks.append(CheckResult(
            label=f"All {len(usemtls)} usemtl references defined in MTL",
            ok=True,
        ))
    else:
        checks.append(CheckResult(
            label="No usemtl references in OBJ (no material assignments)",
            ok=True,
        ))

    # Check 4 - map_* files exist
    _progress("checking textures...")
    missing_tex: list[tuple[str, int, str, str]] = []
    total_maps = 0
    for mtl_name, d in mtl_data.items():
        for (ln, directive, fname) in d.maps:
            total_maps += 1
            tex_path = (base_dir / fname).resolve()
            if not tex_path.is_file():
                missing_tex.append((mtl_name, ln, directive, fname))
    if missing_tex:
        errors += 1
        sub = [
            f"{mtl_name}:{ln}  {directive} {fname}"
            for (mtl_name, ln, directive, fname) in missing_tex[:10]
        ]
        if len(missing_tex) > 10:
            sub.append(f"... (+{len(missing_tex) - 10} more)")
        checks.append(CheckResult(
            label=f"Texture files not found: {len(missing_tex)}/{total_maps}",
            ok=False,
            sub_items=sub,
        ))
    elif total_maps:
        checks.append(CheckResult(
            label=f"All {total_maps} texture references resolve to existing files",
            ok=True,
        ))
    else:
        checks.append(CheckResult(label="No texture references in MTL", ok=True))

    # Check 5 - material names that violate spec character rules.
    # Catches both embedded spaces (extra tokens after the directive)
    # and non-alphanumeric characters in the single-token name (quotes,
    # brackets, dots, hyphens, etc.). The OBJ/MTL spec explicitly
    # allows alphanumeric + underscore; everything else is outside the
    # allowed character set.
    #
    # Scope intentionally limited to usemtl and newmtl, where the name
    # is unambiguously a single token. mtllib accepts multiple files
    # and map_* accepts flag arguments, so detection there would need
    # heuristics and risk false positives; not in scope here.
    suspicious_total = (
        len(obj.suspicious_usemtls)
        + sum(len(d.suspicious_newmtls) for d in mtl_data.values())
    )
    if suspicious_total:
        errors += 1
        sub: list[str] = []
        for (ln, full, reason) in obj.suspicious_usemtls[:5]:
            sub.append(f"OBJ:{ln}: usemtl {full!r} ({reason})")
        for mtl_name, d in mtl_data.items():
            for (ln, full, reason) in d.suspicious_newmtls[:5]:
                sub.append(f"{mtl_name}:{ln}: newmtl {full!r} ({reason})")
        if suspicious_total > len(sub):
            sub.append(f"... (+{suspicious_total - len(sub)} more)")
        checks.append(CheckResult(
            label=(
                f"Material names violating spec character rules: "
                f"{suspicious_total}"
            ),
            ok=False,
            sub_items=sub,
        ))
    else:
        checks.append(CheckResult(
            label="All material names within spec character rules",
            ok=True,
        ))

    _progress("done")

    return ValidationResult(
        obj_path=obj_path,
        base_dir=base_dir,
        v_count=obj.v_count,
        vt_count=obj.vt_count,
        vn_count=obj.vn_count,
        mtllib_count=len(obj.mtllibs),
        usemtl_unique_count=len(set(obj.usemtls)),
        checks=checks,
        error_count=errors,
    )


def _render_face_error(entry: tuple[int, str, int, int]) -> str:
    """Render one face-index error for the text report."""
    ln, axis, idx, cnt = entry
    if idx == 0:
        return f"line {ln}: {axis}-index 0 (must be >= 1)"
    return f"line {ln}: {axis}-index {idx} > count {cnt}"


# --- output helpers ------------------------------------------------------


def format_result_lines(result: ValidationResult, quiet: bool = False) -> list[str]:
    """Render a ValidationResult to a list of output lines, matching the
    original CLI format. Used by both the CLI and the GUI."""
    lines: list[str] = []
    if not quiet:
        lines.append("=== Reference integrity check ===")
        lines.append(f"OBJ: {result.obj_path}")
        lines.append(f"Working dir: {result.base_dir}")
        lines.append("")
        lines.append(
            f"OBJ counts: v={result.v_count}  vt={result.vt_count}  "
            f"vn={result.vn_count}"
        )
        lines.append(
            f"OBJ refs:   mtllib={result.mtllib_count}  "
            f"usemtl (unique)={result.usemtl_unique_count}"
        )
        lines.append("")
        for check in result.checks:
            tag = "[OK]  " if check.ok else "[FAIL]"
            head = f"{tag} {check.label}"
            if check.detail:
                head += f" - {check.detail}"
            lines.append(head)
            for item in check.sub_items:
                lines.append(f"       {item}")
        lines.append("")

    if result.overall_ok:
        lines.append("=== Reference integrity OK ===")
    else:
        lines.append(f"=== {result.error_count} check(s) failed ===")
    return lines


def write_text_report(result: ValidationResult, out_path: Path) -> None:
    """Write a single-file plain-text report.

    Kept for backwards compatibility and direct API use. Atomic via
    .tmp + replace so a crash mid-write leaves no truncated file.
    Callers should ensure the parent directory exists.
    """
    write_combined_text_report([result], out_path)


def write_combined_text_report(
    results: list[ValidationResult],
    out_path: Path,
) -> None:
    """Write one plain-text report covering one or more validation results.

    Each result is rendered with format_result_lines and separated from
    the next by a horizontal rule, so the file reads top-to-bottom as a
    batch report. Atomic via .tmp + replace.
    """
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    blocks: list[str] = []
    for i, result in enumerate(results):
        if i > 0:
            blocks.append("")
            blocks.append("-" * 72)
            blocks.append("")
        blocks.extend(format_result_lines(result))
    tmp.write_text("\n".join(blocks) + "\n", encoding="utf-8")
    tmp.replace(out_path)


def write_csv_report(result: ValidationResult, out_path: Path) -> None:
    """Write a CSV report for a single validation result.

    Thin wrapper around write_combined_csv_report for callers that
    only need to serialise one result. Atomic via .tmp + replace.
    """
    write_combined_csv_report([result], out_path)


def write_combined_csv_report(
    results: list[ValidationResult],
    out_path: Path,
) -> None:
    """Write a single CSV covering one or more validation results.

    One row per check, with the OBJ path repeated on each row so a
    spreadsheet user can sort/filter by file. Used for batch runs to
    capture the whole run in one sheet.

    Atomic via .tmp + replace. Empty results produce a header-only
    CSV so the file always exists with a known schema.
    """
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "check", "status", "detail", "sub_items"])
        for result in results:
            for check in result.checks:
                w.writerow([
                    str(result.obj_path),
                    check.label,
                    "OK" if check.ok else "FAIL",
                    check.detail,
                    "; ".join(check.sub_items),
                ])
    tmp.replace(out_path)


# --- CLI -----------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate_obj_refs.py",
        description=(
            "Validate the reference integrity of an OBJ bundle. "
            "Checks that every face index, mtllib, usemtl and map_* "
            "directive points to something that actually exists. "
            "Complements GUI viewers (MeshLab, Blender) and format "
            "identifiers (DROID, Siegfried)."
        ),
        epilog=(
            "Exit codes: 0 = all checks passed, 1 = one or more "
            "failed, 2 = usage or I/O error. See README.md for details."
        ),
    )
    parser.add_argument(
        "obj_path",
        metavar="OBJ_PATH",
        help=(
            "Path to the .obj file to validate. Sibling .mtl files "
            "and texture files are resolved relative to this file's "
            "directory."
        ),
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Only print the final summary line (respects exit code).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.4.0",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    obj_path = Path(args.obj_path).expanduser().resolve()
    if not obj_path.is_file():
        print(f"[FAIL] OBJ file not found: {obj_path}", file=sys.stderr)
        return 2

    try:
        result = validate_obj_path(obj_path)
    except FileNotFoundError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2

    for line in format_result_lines(result, quiet=args.quiet):
        print(line)
    return 0 if result.overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
