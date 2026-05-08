#!/usr/bin/env python3
"""
test_validate_obj_refs.py - Unit tests for the OBJ reference-integrity validator.

Stdlib only (uses unittest, tempfile, pathlib). Run with:

    python3 -m unittest test_validate_obj_refs.py
    python3 -m unittest -v test_validate_obj_refs.py    # verbose
"""

from __future__ import annotations

import platform
import tempfile
import unittest
from pathlib import Path

from validate_obj_refs import (
    MAX_FACE_ERRORS_TRACKED,
    ValidationResult,
    format_result_lines,
    parse_mtl,
    parse_obj,
    validate_obj_path,
    write_combined_csv_report,
    write_combined_text_report,
    write_csv_report,
    write_text_report,
)


# --- helpers --------------------------------------------------------------


def _write(p: Path, content: str) -> None:
    p.write_text(content, encoding="utf-8")


def _check_named(result: ValidationResult, contains: str):
    """Find the first check whose label contains the substring."""
    for c in result.checks:
        if contains.lower() in c.label.lower():
            return c
    raise AssertionError(
        f"No check matched {contains!r}. "
        f"Available labels: {[c.label for c in result.checks]}"
    )


class _TempCase(unittest.TestCase):
    """Base class that sets up an isolated temp folder per test."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()


# --- minimal happy path ---------------------------------------------------


class TestMinimal(_TempCase):

    def test_clean_obj_no_materials(self) -> None:
        """OBJ with 3 vertices, 1 face, no MTL: all checks pass."""
        obj = self.dir / "test.obj"
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        result = validate_obj_path(obj)
        self.assertTrue(result.overall_ok)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.v_count, 3)
        self.assertEqual(result.mtllib_count, 0)
        self.assertEqual(result.usemtl_unique_count, 0)


# --- Bug 1a: v_idx == 0 -------------------------------------------------


class TestZeroIndexBug(_TempCase):
    """OBJ indices are 1-based; index 0 is invalid and must be flagged."""

    def test_face_index_zero_is_flagged(self) -> None:
        obj = self.dir / "test.obj"
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 0 1 2\n")
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)
        check = _check_named(result, "face")
        self.assertFalse(check.ok)

    def test_vt_index_zero_is_flagged(self) -> None:
        obj = self.dir / "test.obj"
        _write(
            obj,
            "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "vt 0 0\nvt 1 0\nvt 0 1\n"
            "f 1/0 2/2 3/3\n",
        )
        result = validate_obj_path(obj)
        check = _check_named(result, "face")
        self.assertFalse(check.ok)

    def test_face_negative_index_skipped(self) -> None:
        """Negative (relative) indices are recognised but not validated."""
        obj = self.dir / "test.obj"
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf -1 -2 -3\n")
        result = validate_obj_path(obj)
        check = _check_named(result, "face")
        self.assertTrue(check.ok)


# --- Bug 1b: UTF-8 BOM ----------------------------------------------------


class TestBOM(_TempCase):
    """A UTF-8 BOM at the start of the file must not break parsing."""

    def test_bom_does_not_eat_first_vertex(self) -> None:
        obj = self.dir / "test.obj"
        # Write a BOM followed by valid content.
        content = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        obj.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        result = validate_obj_path(obj)
        self.assertEqual(
            result.v_count, 3,
            "BOM caused first vertex to be lost",
        )
        self.assertTrue(result.overall_ok)

    def test_bom_in_mtl_does_not_eat_first_newmtl(self) -> None:
        mtl = self.dir / "mat.mtl"
        mtl.write_bytes(b"\xef\xbb\xbf" + b"newmtl mat0\nKa 1 1 1\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertTrue(result.overall_ok)


# --- face index in/out of range ------------------------------------------


class TestFaceIndices(_TempCase):

    def test_face_index_within_range(self) -> None:
        obj = self.dir / "test.obj"
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        result = validate_obj_path(obj)
        check = _check_named(result, "face")
        self.assertTrue(check.ok)

    def test_face_index_out_of_range(self) -> None:
        obj = self.dir / "test.obj"
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 5\n")
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)


# --- mtllib references ----------------------------------------------------


class TestMtllib(_TempCase):

    def test_mtllib_missing(self) -> None:
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib nonexistent.mtl\n"
            "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)
        check = _check_named(result, "MTL")
        self.assertFalse(check.ok)

    def test_mtllib_present(self) -> None:
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\nKa 1 1 1\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertTrue(result.overall_ok)


# --- usemtl / newmtl matching --------------------------------------------


class TestUsemtlMatching(_TempCase):

    def test_usemtl_matches(self) -> None:
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertTrue(result.overall_ok)

    def test_usemtl_mismatch(self) -> None:
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl other_mat\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)

    def test_artec_quoted_usemtl_quirk(self) -> None:
        """Strict literal matching: 'name' (with quotes) does not match name."""
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\nnewmtl material_1\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            'mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n'
            'usemtl mat0\nf 1 2 3\n'
            'usemtl "material_1"\n',
        )
        result = validate_obj_path(obj)
        self.assertFalse(
            result.overall_ok,
            "Quoted usemtl must NOT match unquoted newmtl",
        )

    def test_no_usemtl_passes(self) -> None:
        obj = self.dir / "test.obj"
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        result = validate_obj_path(obj)
        self.assertTrue(result.overall_ok)


# --- texture references ---------------------------------------------------


class TestTextures(_TempCase):

    def test_texture_present(self) -> None:
        (self.dir / "tex.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\nmap_Kd tex.png\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertTrue(result.overall_ok)

    def test_texture_missing(self) -> None:
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\nmap_Kd nonexistent.png\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)

    def test_texture_with_flag_args(self) -> None:
        """map_Kd may have flags before the filename; we take the last token."""
        (self.dir / "tex.png").write_bytes(b"\x89PNG")
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\nmap_Kd -clamp on -mm 0.0 1.0 tex.png\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertTrue(result.overall_ok)

    def test_case_mismatch_on_case_sensitive_fs(self) -> None:
        """Linux/macOS strict; .TIF in MTL vs .tif on disk should fail."""
        if platform.system() == "Windows":
            self.skipTest("Filesystem is case-insensitive on Windows")
        (self.dir / "tex.tif").write_bytes(b"")
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\nmap_Kd tex.TIF\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)


# --- Bug 4a: error list cap ----------------------------------------------


class TestErrorListCap(_TempCase):
    """face_idx_errors must not grow unbounded on heavily corrupt input."""

    def test_many_face_errors_capped_in_storage_but_total_correct(self) -> None:
        # 3 vertices, lots of out-of-range face references.
        # Each face line has 3 vertex refs, each becomes 1 error: total = 3 * n_faces.
        n_faces = (MAX_FACE_ERRORS_TRACKED + 500) // 3 + 1
        expected_total = n_faces * 3
        lines = ["v 0 0 0", "v 1 0 0", "v 0 1 0"]
        for _ in range(n_faces):
            lines.append("f 100 200 300")
        obj = self.dir / "test.obj"
        _write(obj, "\n".join(lines) + "\n")

        result = validate_obj_path(obj)
        check = _check_named(result, "face")
        self.assertFalse(check.ok)
        # The label must reflect the true total (not the cap), to make
        # corruption-magnitude visible to the user.
        self.assertIn(
            str(expected_total), check.label,
            f"Expected label to mention total {expected_total}; got: {check.label}",
        )


# --- Bug 1c: material names with embedded spaces -----------------------


class TestSpecCompliance(_TempCase):
    """Per OBJ/MTL spec: material names use [A-Za-z0-9_] only.

    Anything else (blanks, quotes, brackets, hyphens, dots, ...) is a
    spec violation. The check covers usemtl in the OBJ and newmtl in
    each loaded MTL.
    """

    def test_usemtl_with_embedded_space_is_flagged(self) -> None:
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl my material\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)
        check = _check_named(result, "spec character rules")
        self.assertFalse(check.ok)
        self.assertTrue(any("embedded space" in s for s in check.sub_items))

    def test_newmtl_with_embedded_space_is_flagged(self) -> None:
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl my material\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)
        check = _check_named(result, "spec character rules")
        self.assertFalse(check.ok)

    def test_quoted_usemtl_is_flagged_as_non_alphanumeric(self) -> None:
        """The Artec-export quirk: usemtl 'material_1' (with quotes)
        contains characters outside [A-Za-z0-9_]."""
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl material_1\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            'mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n'
            'usemtl "material_1"\nf 1 2 3\n',
        )
        result = validate_obj_path(obj)
        self.assertFalse(result.overall_ok)
        check = _check_named(result, "spec character rules")
        self.assertFalse(check.ok)
        self.assertTrue(any("non-alphanumeric" in s for s in check.sub_items))

    def test_hyphen_and_dot_are_allowed_common_practice(self) -> None:
        """Hyphens and dots are technically outside the strict spec but
        ubiquitous in real exports (Blender auto-numbering: Material.001;
        human-readable names: wood-grain). The validator accepts them."""
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl wood-grain\nnewmtl Material.001\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl wood-grain\nf 1 2 3\nusemtl Material.001\n",
        )
        result = validate_obj_path(obj)
        check = _check_named(result, "spec character rules")
        self.assertTrue(
            check.ok,
            f"hyphen/dot should pass the relaxed check; got: {check.label}",
        )

    def test_bracket_in_name_is_flagged(self) -> None:
        """Brackets are clearly outside both strict and common-practice
        identifier conventions."""
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat[1]\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat[1]\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        check = _check_named(result, "spec character rules")
        self.assertFalse(check.ok)

    def test_clean_alphanumeric_names_pass(self) -> None:
        mtl = self.dir / "mat.mtl"
        _write(mtl, "newmtl mat0\nnewmtl my_other_material\n")
        obj = self.dir / "test.obj"
        _write(
            obj,
            "mtllib mat.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "usemtl mat0\nf 1 2 3\n",
        )
        result = validate_obj_path(obj)
        check = _check_named(result, "spec character rules")
        self.assertTrue(check.ok)


# --- defensive validate_obj_path ----------------------------------------


class TestDefensiveValidateObjPath(_TempCase):
    """Bug 2h: validate_obj_path should raise on missing input, not crash later."""

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            validate_obj_path(self.dir / "does_not_exist.obj")


# --- format_result_lines (output formatting) ----------------------------


class TestFormatResultLines(_TempCase):

    def test_clean_output_contains_ok_marker(self) -> None:
        obj = self.dir / "test.obj"
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        result = validate_obj_path(obj)
        lines = format_result_lines(result)
        self.assertTrue(any("Reference integrity OK" in line for line in lines))

    def test_quiet_output(self) -> None:
        obj = self.dir / "test.obj"
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        result = validate_obj_path(obj)
        lines = format_result_lines(result, quiet=True)
        # Quiet mode should produce only the summary line, not the full report.
        self.assertEqual(len(lines), 1)
        self.assertIn("OK", lines[0])

    def test_failed_output_contains_check_count(self) -> None:
        obj = self.dir / "test.obj"
        _write(obj, "mtllib missing.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        result = validate_obj_path(obj)
        lines = format_result_lines(result)
        self.assertTrue(any("check(s) failed" in line for line in lines))


class TestCsvReports(_TempCase):
    """write_csv_report and write_combined_csv_report produce the right
    CSV shape: header row + one row per check, with file path repeated."""

    def _make_clean_obj(self, name: str = "test.obj") -> Path:
        obj = self.dir / name
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        return obj

    def test_per_file_csv_has_one_row_per_check(self) -> None:
        obj = self._make_clean_obj()
        result = validate_obj_path(obj)
        out = self.dir / "report.csv"
        write_csv_report(result, out)

        text = out.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln]
        # Header + one row per check
        self.assertEqual(lines[0], "file,check,status,detail,sub_items")
        self.assertEqual(len(lines) - 1, len(result.checks))

    def test_combined_csv_concatenates_results(self) -> None:
        obj_a = self._make_clean_obj("a.obj")
        obj_b = self._make_clean_obj("b.obj")
        result_a = validate_obj_path(obj_a)
        result_b = validate_obj_path(obj_b)

        out = self.dir / "combined.csv"
        write_combined_csv_report([result_a, result_b], out)

        text = out.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln]
        # Header + checks_a + checks_b
        expected_rows = len(result_a.checks) + len(result_b.checks)
        self.assertEqual(lines[0], "file,check,status,detail,sub_items")
        self.assertEqual(len(lines) - 1, expected_rows)
        # Both file paths appear in the combined CSV
        self.assertIn("a.obj", text)
        self.assertIn("b.obj", text)

    def test_combined_csv_empty_results_writes_header_only(self) -> None:
        out = self.dir / "empty.csv"
        write_combined_csv_report([], out)
        text = out.read_text(encoding="utf-8")
        self.assertEqual(text.strip(), "file,check,status,detail,sub_items")


class TestTextReports(_TempCase):
    """write_text_report and write_combined_text_report produce text output
    that matches format_result_lines, separated by horizontal rules."""

    def _make_clean_obj(self, name: str = "test.obj") -> Path:
        obj = self.dir / name
        _write(obj, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        return obj

    def test_per_file_text_matches_format_result_lines(self) -> None:
        obj = self._make_clean_obj()
        result = validate_obj_path(obj)
        out = self.dir / "report.txt"
        write_text_report(result, out)
        expected = "\n".join(format_result_lines(result)) + "\n"
        self.assertEqual(out.read_text(encoding="utf-8"), expected)

    def test_combined_text_separates_results_with_rule(self) -> None:
        result_a = validate_obj_path(self._make_clean_obj("a.obj"))
        result_b = validate_obj_path(self._make_clean_obj("b.obj"))
        out = self.dir / "combined.txt"
        write_combined_text_report([result_a, result_b], out)

        text = out.read_text(encoding="utf-8")
        # Each OBJ name appears in its block.
        self.assertIn("a.obj", text)
        self.assertIn("b.obj", text)
        # A horizontal rule separates the two blocks.
        self.assertIn("-" * 72, text)


if __name__ == "__main__":
    unittest.main()
