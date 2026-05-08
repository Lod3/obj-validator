# OBJ Reference Integrity Validator

Toolkit for validating the reference integrity of OBJ bundles (face indices, `mtllib`, `usemtl`, `map_*` references). Part of the 3D Preservation Research project.

The toolkit ships in three forms:

1. **`validate_obj_refs.py`** - command-line script. Stdlib-only Python.
2. **`validate_obj_gui.py`** - desktop GUI on top of the same checks. Tkinter, multilingual (NL/FR/EN).
3. **Standalone executable** built from the GUI with PyInstaller. No Python install required for end users.

---

## For end users (no Python install)

Download the executable for your platform from the project release folder:

- **Windows**: `validate_obj_gui.exe` - double-click to run.
- **macOS**: `validate_obj_gui.app` - double-click to run. On first launch you may need to right-click and choose "Open" to bypass Gatekeeper.
- **Linux**: `validate_obj_gui` - right-click, Properties, open "Permissions" tab and check "Allow executing file as program". Or mark executable with `chmod +x validate_obj_gui`, and double-click to open.

On first launch you are asked to pick an interface language (NL / FR / EN). The choice is saved in `~/.validate_obj_gui_settings.json` and can be changed later via Options > Language.

### Using the GUI

- **Add file** / **Add folder (recursive)** to load OBJ files into the table. Folders are scanned for `.obj` recursively.
- **Remove selection** (or press Delete / Backspace on the selected rows) takes individual files out of the list without wiping the rest. Use Ctrl/Shift to select multiple rows.
- **Output folder (required)**: pick a folder via Browse. The combined report files land here. There is no per-file output mode; one report per run covers the whole batch.
- **Report formats (1 file per run)**: tick **Text (.txt)** (default on) and/or **CSV (.csv)** (default off). With one tick you get one file; with both you get a `.txt` and a `.csv` side by side. Filenames are `validation_batch_<date>_<time>.txt` and `.csv`.
- **Validate** starts the run. Progress streams to the log panel: stage messages plus a tick every 5 million lines for large files.
- **Cancel** stops the run cleanly between files. The currently-processing file finishes naturally so its data is included in the combined report. Remaining files stay as `Waiting`; click Validate again to resume.

<img width="748" height="598" alt="image" src="https://github.com/user-attachments/assets/4e1aa315-3e81-47fb-8482-fca855e3ea83" />
&nbsp;
<img width="748" height="598" alt="Scherm­afbeelding 2026-05-08 om 18 47 11" src="https://github.com/user-attachments/assets/1a96c8a0-6520-4c32-9f6e-2051407383ba" />
&nbsp;
<img width="748" height="598" alt="image" src="https://github.com/user-attachments/assets/7e21e138-4917-4e1d-a0b7-92fde86b8d30" />


## For developers (run from source)

Requires Python 3.10 or newer with `tkinter` available.

```bash
git clone <repo-url>
cd tools/
python3 validate_obj_refs.py path/to/MODEL.obj           # CLI
python3 validate_obj_gui.py                               # GUI
```

If `python3` complains about missing `_tkinter`:

- Fedora / RHEL: `sudo dnf install python3-tkinter`
- Debian / Ubuntu: `sudo apt install python3-tk`
- macOS (python.org installer): tkinter is bundled
- macOS (Homebrew Python): `brew install python-tk@3.13` (match your Python version)
- Windows (python.org installer): tkinter is bundled

CLI exit codes: `0` all checks passed, `1` one or more failed, `2` usage or I/O error.

---

## Building the standalone executable yourself

PyInstaller cannot cross-compile. To produce a Windows `.exe` you need a Windows machine; for a macOS `.app` you need a Mac; for a Linux binary you need Linux. The same `build.py` script works on all three.

Each platform follows the same three steps: copy the source folder to the target machine, set up a Python venv with PyInstaller, run `python build.py`. Concrete commands per platform below.

### Linux

Copy the source folder to the Linux machine, e.g. `~/scripts/build-validator/`. Then in a terminal:

```bash
cd ~/scripts/build-validator
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install pyinstaller
python build.py
```

Output: `dist/validate_obj_gui` (~16 MB ELF binary).

If `python3 -m venv` fails on Fedora with a missing `ensurepip` error: `sudo dnf install python3-tkinter` covers most missing pieces in one go.

### Windows

Copy the source folder to the Windows machine, e.g. `C:\Users\<you>\scripts\build-validator\`. Open PowerShell:

```powershell
cd C:\Users\<you>\scripts\build-validator
python -m venv .venv-build
.venv-build\Scripts\activate
pip install pyinstaller
python build.py
```

Output: `dist\validate_obj_gui.exe` (~25 MB single-file executable).

Prerequisite: Python 3.10+ installed via the [python.org installer](https://www.python.org/downloads/windows/) with "Add Python to PATH" ticked. Tkinter is bundled.

### macOS

Copy the source folder to the Mac, e.g. `~/scripts/build-validator/`. Transfer methods that work: AirDrop, USB, NAS share, or RustDesk file-transfer. Open Terminal:

```bash
cd ~/scripts/build-validator
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install pyinstaller
python build.py
```

Output in `dist/`:
- `validate_obj_gui.app` (~25 MB app bundle, double-clickable in Finder)
- `validate_obj_gui` (standalone binary for terminal use)

Prerequisites: Python 3.10+ from the [python.org installer](https://www.python.org/downloads/macos/) (the .pkg), not Homebrew. The python.org installer brings Tkinter along; Homebrew Python often needs `python-tk@3.x` separately.

### Build flags

`python build.py` accepts two optional flags:

- `--clean` removes `build/` and `dist/` before rebuilding. Use after a script update to avoid stale caches.
- `--debug` keeps the console window visible on Windows/macOS and enables verbose PyInstaller output. Useful when the GUI silently crashes on launch and you need to see the traceback.

### Per-platform notes

**Windows:** the build is silent (no console window pops up next to the GUI). For debugging during development use `python build.py --debug` to keep a visible console, which prints uncaught Python errors. Antivirus tools sometimes flag fresh PyInstaller binaries as suspicious. If your colleagues see a SmartScreen warning ("Windows protected your PC"), they can click "More info" then "Run anyway", or you can sign the executable with a code-signing certificate to remove the warning permanently.

**macOS:** Apple requires that .app bundles distributed outside the App Store be either notarised or run with a manual right-click > Open the first time. Without notarisation, double-clicking will show "cannot be opened because the developer cannot be verified". Notarisation requires an Apple Developer account ($99/year). When and how this blocks depends on the Macos version. it was tested it on Tahoe, the app always opens after the second time.

**Linux:** the binary is a statically-bundled ELF that includes its own Python interpreter and tkinter. It runs on most modern distributions without further dependencies. Tested on Fedora 43. On older glibc versions the binary may not start; in that case build on the oldest target distribution.

---

## What the tool checks

Five reference-integrity and spec-compliance checks per OBJ file:

1. Face indices (`f`) fall within the range of `v` / `vt` / `vn` counts in the file. Index 0 is invalid (OBJ uses 1-based indexing) and is reported.
2. Every `mtllib` reference points to an existing `.mtl` file in the same folder.
3. Every `usemtl` in the OBJ matches a `newmtl` definition in one of the loaded MTLs.
4. Every `map_*` directive in the MTLs points to an existing texture file.
5. Every `usemtl` and `newmtl` name uses only allowed characters: alphanumeric, underscore, hyphen and dot. Embedded spaces, quotes, brackets, parentheses, slashes and other punctuation are flagged as spec violations. (Strict spec is alphanumeric + underscore only; hyphen and dot are accepted as common-practice exceptions: hyphen for human-readable names like `wood-grain`, dot for Blender auto-numbering like `Material.001`.)

These checks complement (not replace) GUI viewers like MeshLab/Blender and format identifiers like DROID/Siegfried. Viewers catch missing textures visually, but silently ignore other reference issues. Identifiers verify PRONOM signatures but not internal consistency. This tool fills that gap with deterministic, scriptable checks suitable for preservation workflows and bulk validation.

## Read-only guarantee

The validator never modifies the OBJ, MTL, or texture files it inspects. All source-file access is read-only:

- `validate_obj_refs.py` opens OBJ and MTL files with mode `"r"` (read-only) and only ever calls `is_file()` / `resolve()` (metadata) on textures.
- The GUI worker thread uses the same code path and adds no writes.
- The only files the tool **does** create are its own report outputs: `validation_batch_<date>_<time>.txt` and/or `validation_batch_<date>_<time>.csv`. These land in the user-chosen output folder, never next to the OBJ files. Reports are written via atomic `.tmp` + rename so a crash mid-write leaves no truncated file.

This matches preservation requirements where the archived bundle must remain bit-identical before and after inspection. If you need a stronger guarantee, hash the source files before and after a validation run and compare; the hashes will be identical.

## How validation works

The validator is a single-pass line-based parser written in pure Python (stdlib only, no third-party libraries). It opens the OBJ file with UTF-8 decoding (errors replaced, not raised), iterates over every line and dispatches on the first whitespace-delimited token. Comments (`#`) and blank lines are skipped.

**OBJ keywords tracked:**

- `v` / `vt` / `vn`: counted (positions / texture coordinates / normals).
- `f`: each vertex reference is split on `/` into v / vt / vn indices. Positive indices that exceed the running counts are recorded as out-of-range. Negative (relative) indices are recognised but not validated; they are rare in modern exports.
- `mtllib`: each filename token is collected as an MTL reference.
- `usemtl`: the material name token (literal, including any quotes or punctuation) is collected.

All other keywords (`o`, `g`, `s`, `l`, `p`, etc.) are ignored: they do not affect reference integrity.

**MTL keywords tracked:**

- `newmtl`: the material name token is collected.
- Texture directives: `map_Kd`, `map_Ka`, `map_Ks`, `map_Ns`, `map_d`, `map_Bump`, `bump`, `norm`, `disp`, `decal`, `map_Pr`, `map_Pm`, `map_Ps`, `map_Ke`. Matching is case-insensitive on the directive token. The filename is taken as the last whitespace-delimited token on the line, which correctly skips any preceding flag arguments (e.g. `map_Kd -clamp on -mm 0.0 1.0 wood.png`).

All other MTL keywords (`Ka`, `Kd`, `Ks`, `Ns`, `d`, `illum`, ...) are read but not validated; they describe shading parameters, not file references.

**Path resolution and matching:**

- MTL and texture filenames in the source files are resolved relative to the OBJ's parent folder (the same convention MeshLab and Blender use).
- Filename existence is checked via the host filesystem, so case-sensitivity follows the host: case-sensitive on Linux and macOS (default APFS configuration), case-insensitive on Windows (NTFS default). A mismatch in casing (e.g. `texture.TIF` in the MTL vs. `texture.tif` on disk) will surface as missing on Linux but pass silently on Windows.
- `usemtl` and `newmtl` matching is strict literal string comparison. The OBJ specification describes material names as alphanumeric tokens with underscores; the spec does not define a quote-stripping or escape mechanism. The validator therefore treats `"material_1"` (with quotes) and `material_1` (without) as different names, which mirrors the behaviour of MeshLab and other parsers. A separate spec-compliance check (number 5 above) flags any name containing characters outside `[A-Za-z0-9_]`, so non-spec names typically fail twice: once on the lookup mismatch (check 3) and once on the character-set violation (check 5). Both failures point at the same root cause.
- Negative (relative) face indices like `f -1 -2 -3` are recognised but not validated. They are legal per the OBJ spec but rare in modern exports.
- Line continuations (`\` at end of line) are not interpreted; the next line is treated as a separate (likely unrecognised) line. Also rare in modern exports.

**What the tool does NOT check:**

- Geometry quality (degenerate faces, non-manifold edges, normal direction).
- Semantic correctness of materials (whether the colour values are sensible).
- Whether the OBJ describes a coherent 3D model rather than random triangles.
- Image content of texture files (whether they are valid PNG/JPEG/TIFF, sufficient resolution, etc.).

These belong to the broader validation workflow, where tools like trimesh, Assimp, and viewers like MeshLab take over.

## Libraries used

The validator and the GUI are written against the **Python standard library only**. No third-party packages are imported at runtime. This keeps the tool installable without `pip`, easy to audit, and unaffected by upstream package churn.

**Runtime imports:**

- `argparse`, `pathlib`, `dataclasses`, `sys`, `typing`, `re` - CLI parsing, path handling, structured data, name-pattern matching.
- `csv` - writing the combined CSV report.
- `tkinter` (incl. `tkinter.ttk`, `tkinter.filedialog`, `tkinter.messagebox`) - desktop GUI. Bundled with most Python installs; on Fedora available via `python3-tkinter`, on Debian/Ubuntu via `python3-tk`.
- `threading`, `queue` - background validation worker so the GUI stays responsive on large OBJ files.
- `json`, `datetime` - persistent language preference and timestamped log entries.

**Build-time dependency:**

- [PyInstaller](https://pyinstaller.org/) - only needed if you want to produce a standalone executable. Installed inside the build venv (`pip install pyinstaller`). Not used at runtime: the produced executable bundles its own Python interpreter and standard library, so end users have nothing to install.

**Validators we deliberately do NOT depend on:**

- [trimesh](https://github.com/mikedh/trimesh) and [Assimp](https://github.com/assimp/assimp) - both are excellent OBJ parsers. We avoid them by design: they would parse the OBJ a second time, which defeats the purpose of an independent integrity check. The broader validation workflow uses them in parallel as cross-checks; this tool fills the gap they leave open (reference integrity).
- Image libraries (Pillow, OpenCV) - only file existence is checked, not image content.

---
