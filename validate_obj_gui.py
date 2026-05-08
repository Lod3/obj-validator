#!/usr/bin/env python3
"""
validate_obj_gui.py - Tkinter GUI for validate_obj_refs.

Purpose:
  Lower the barrier for archive workers and other non-developers who
  need to run reference-integrity checks on OBJ bundles. Wraps the
  same checks as the CLI (validate_obj_refs.py) in a basic desktop
  window with file/folder pickers, a results table, a mandatory
  output-folder selector, a combined-report format chooser (txt/csv)
  and a streaming log panel.

Design choices (kept simple on purpose):
  - Stdlib only (uses tkinter, threading, queue, datetime, json).
  - Single file. No external assets.
  - Imports the validator from validate_obj_refs (must sit in the
    same directory).
  - Validation runs in a background worker thread to keep the UI
    responsive on large OBJ files. Communication with the UI thread
    happens via a queue, drained from a Tk after()-loop.
  - All Tk-variable reads happen on the main thread before the worker
    starts; values are snapshotted and passed as worker arguments.
    Tk variables and widgets are NEVER touched from the worker.
  - The current language is also snapshotted at worker start, so a
    mid-flight language switch does not produce mixed-language logs.
  - One combined report per run (txt and/or csv) is written via
    write_combined_text_report and write_combined_csv_report from
    validate_obj_refs, both of which use atomic .tmp + replace so a
    crash mid-write leaves no truncated file.
  - Settings (language preference) stored in a JSON dotfile in the
    user's home directory.

Usage:
    python validate_obj_gui.py

Requires:
  - Python 3.10+
  - tkinter (bundled with most Python installs; on some Linux
    distros install via the system package manager, e.g.
    `sudo dnf install python3-tkinter` on Fedora,
    `sudo apt install python3-tk` on Debian/Ubuntu).
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from validate_obj_refs import (
    ValidationResult,
    format_result_lines,
    validate_obj_path,
    write_combined_csv_report,
    write_combined_text_report,
)


SUPPORTED_EXTENSIONS = (".obj",)
SETTINGS_PATH = Path.home() / ".validate_obj_gui_settings.json"
DEFAULT_LANG = "en"


# --- Translations --------------------------------------------------------


LANGUAGES: dict[str, dict[str, str]] = {
    "nl": {
        "lang_name": "Nederlands",
        "title": "OBJ Reference Integrity Validator",
        "menu_options": "Opties",
        "menu_language": "Taal",
        "btn_add_file": "Bestand toevoegen...",
        "btn_add_folder": "Map toevoegen (recursief)...",
        "btn_remove_selected": "Verwijder selectie",
        "btn_clear": "Wis lijst",
        "btn_validate": "Valideren",
        "btn_cancel": "Annuleren",
        "btn_browse": "Bladeren...",
        "col_status": "Status",
        "col_fails": "# FAIL",
        "col_format": "Formaat",
        "col_path": "Pad",
        "out_label": "Output-folder (verplicht)",
        "per_file_label": "Rapport-formaten (1 bestand per run)",
        "write_txt": "Tekst (.txt)",
        "write_csv": "CSV (.csv)",
        "log_label": "Log",
        "status_waiting": "Wachtend",
        "status_processing": "Bezig",
        "status_ok": "OK",
        "status_fail": "FAIL",
        "status_error": "Fout",
        "dlg_pick_files": "Selecteer een of meer OBJ-bestanden",
        "dlg_pick_folder": "Selecteer een map (subfolders worden meegescand)",
        "dlg_pick_output": "Selecteer output-folder voor rapport-bestanden",
        "filter_obj": "OBJ-bestanden",
        "filter_all": "Alle bestanden",
        "msg_no_files_title": "Geen bestanden",
        "msg_no_files": "Voeg eerst een of meer OBJ-bestanden of een map toe.",
        "msg_no_outdir_title": "Geen output-folder",
        "msg_no_outdir": "Selecteer eerst een output-folder.",
        "msg_bad_outdir_title": "Ongeldige output-folder",
        "msg_bad_outdir_fmt": "Folder bestaat niet: {dir}",
        "msg_running_title": "Validatie loopt",
        "msg_running": "Validatie is bezig. Sluiten kan resulteren in onvolledige rapporten. Toch sluiten?",
        "msg_no_format_title": "Geen output-formaat",
        "msg_no_format": "Selecteer minstens een output-formaat (Tekst en/of CSV).",
        "log_added_fmt": "Toegevoegd: {n} bestand(en).",
        "log_scanned_fmt": "Map gescand: {root}  - {n} OBJ-bestand(en) toegevoegd.",
        "log_cleared": "Lijst gewist.",
        "log_removed_fmt": "Verwijderd uit lijst: {n} bestand(en).",
        "log_start_fmt": "Start validatie van {n} bestand(en).",
        "log_validating_fmt": "Valideren: {name}",
        "log_status_fmt": "  {status}",
        "log_status_with_fails_fmt": "  {status}  ({n} check(s) gefaald)",
        "log_error_fmt": "  Fout: {err}",
        "log_done_fmt": "Validatie afgerond: {ok} OK, {fail} FAIL, {err} fout, {total} totaal.",
        "log_cancel_requested": "Annulering aangevraagd. Worker stopt na het huidige bestand.",
        "log_cancelled": "Validatie geannuleerd door gebruiker.",
        "log_combined_written_fmt": "Rapport geschreven: {path}",
        "log_write_failed_fmt": "  kon niet schrijven: {err}",
        "log_detail_fmt": "--- Detail: {name} ---",
        "log_not_validated_yet": "(nog niet gevalideerd)",
        "log_error_during_fmt": "Fout tijdens validatie: {err}",
        "label_progress_fmt": "Bezig: {done} / {total}",
        "label_done_fmt": "Klaar: {ok} OK, {fail} FAIL, {err} fout / {total}",
        "lang_dialog_title": "Selecteer taal / Select language / Sélectionnez la langue",
    },
    "fr": {
        "lang_name": "Français",
        "title": "OBJ Reference Integrity Validator",
        "menu_options": "Options",
        "menu_language": "Langue",
        "btn_add_file": "Ajouter un fichier...",
        "btn_add_folder": "Ajouter un dossier (récursif)...",
        "btn_remove_selected": "Supprimer la sélection",
        "btn_clear": "Vider la liste",
        "btn_validate": "Valider",
        "btn_cancel": "Annuler",
        "btn_browse": "Parcourir...",
        "col_status": "Statut",
        "col_fails": "# FAIL",
        "col_format": "Format",
        "col_path": "Chemin",
        "out_label": "Dossier de sortie (obligatoire)",
        "per_file_label": "Formats de rapport (1 fichier par exécution)",
        "write_txt": "Texte (.txt)",
        "write_csv": "CSV (.csv)",
        "log_label": "Journal",
        "status_waiting": "En attente",
        "status_processing": "En cours",
        "status_ok": "OK",
        "status_fail": "FAIL",
        "status_error": "Erreur",
        "dlg_pick_files": "Sélectionner un ou plusieurs fichiers OBJ",
        "dlg_pick_folder": "Sélectionner un dossier (sous-dossiers inclus)",
        "dlg_pick_output": "Sélectionner le dossier de sortie pour les rapports",
        "filter_obj": "Fichiers OBJ",
        "filter_all": "Tous les fichiers",
        "msg_no_files_title": "Aucun fichier",
        "msg_no_files": "Ajoutez d'abord un ou plusieurs fichiers OBJ ou un dossier.",
        "msg_no_outdir_title": "Pas de dossier de sortie",
        "msg_no_outdir": "Sélectionnez d'abord un dossier de sortie.",
        "msg_bad_outdir_title": "Dossier de sortie invalide",
        "msg_bad_outdir_fmt": "Le dossier n'existe pas : {dir}",
        "msg_running_title": "Validation en cours",
        "msg_running": "La validation est en cours. Fermer maintenant peut produire des rapports incomplets. Fermer quand même ?",
        "msg_no_format_title": "Pas de format choisi",
        "msg_no_format": "Sélectionnez au moins un format de sortie (Texte et/ou CSV).",
        "log_added_fmt": "Ajouté : {n} fichier(s).",
        "log_scanned_fmt": "Dossier scanné : {root}  - {n} fichier(s) OBJ ajouté(s).",
        "log_cleared": "Liste vidée.",
        "log_removed_fmt": "Retiré de la liste : {n} fichier(s).",
        "log_start_fmt": "Début de validation de {n} fichier(s).",
        "log_validating_fmt": "Validation : {name}",
        "log_status_fmt": "  {status}",
        "log_status_with_fails_fmt": "  {status}  ({n} contrôle(s) en échec)",
        "log_error_fmt": "  Erreur : {err}",
        "log_done_fmt": "Validation terminée : {ok} OK, {fail} FAIL, {err} erreur(s), {total} total.",
        "log_cancel_requested": "Annulation demandée. L'opération s'arrête après le fichier en cours.",
        "log_cancelled": "Validation annulée par l'utilisateur.",
        "log_combined_written_fmt": "Rapport enregistré : {path}",
        "log_write_failed_fmt": "  impossible d'écrire : {err}",
        "log_detail_fmt": "--- Détail : {name} ---",
        "log_not_validated_yet": "(pas encore validé)",
        "log_error_during_fmt": "Erreur lors de la validation : {err}",
        "label_progress_fmt": "En cours : {done} / {total}",
        "label_done_fmt": "Terminé : {ok} OK, {fail} FAIL, {err} erreur(s) / {total}",
        "lang_dialog_title": "Selecteer taal / Select language / Sélectionnez la langue",
    },
    "en": {
        "lang_name": "English",
        "title": "OBJ Reference Integrity Validator",
        "menu_options": "Options",
        "menu_language": "Language",
        "btn_add_file": "Add file...",
        "btn_add_folder": "Add folder (recursive)...",
        "btn_remove_selected": "Remove selection",
        "btn_clear": "Clear list",
        "btn_validate": "Validate",
        "btn_cancel": "Cancel",
        "btn_browse": "Browse...",
        "col_status": "Status",
        "col_fails": "# FAIL",
        "col_format": "Format",
        "col_path": "Path",
        "out_label": "Output folder (required)",
        "per_file_label": "Report formats (1 file per run)",
        "write_txt": "Text (.txt)",
        "write_csv": "CSV (.csv)",
        "log_label": "Log",
        "status_waiting": "Waiting",
        "status_processing": "Processing",
        "status_ok": "OK",
        "status_fail": "FAIL",
        "status_error": "Error",
        "dlg_pick_files": "Select one or more OBJ files",
        "dlg_pick_folder": "Select a folder (subfolders are scanned)",
        "dlg_pick_output": "Select output folder for report files",
        "filter_obj": "OBJ files",
        "filter_all": "All files",
        "msg_no_files_title": "No files",
        "msg_no_files": "Add one or more OBJ files or a folder first.",
        "msg_no_outdir_title": "No output folder",
        "msg_no_outdir": "Select an output folder first.",
        "msg_bad_outdir_title": "Invalid output folder",
        "msg_bad_outdir_fmt": "Folder does not exist: {dir}",
        "msg_running_title": "Validation running",
        "msg_running": "Validation is running. Closing now may leave reports incomplete. Close anyway?",
        "msg_no_format_title": "No output format",
        "msg_no_format": "Select at least one output format (Text and/or CSV).",
        "log_added_fmt": "Added: {n} file(s).",
        "log_scanned_fmt": "Folder scanned: {root}  - {n} OBJ file(s) added.",
        "log_cleared": "List cleared.",
        "log_removed_fmt": "Removed from list: {n} file(s).",
        "log_start_fmt": "Starting validation of {n} file(s).",
        "log_validating_fmt": "Validating: {name}",
        "log_status_fmt": "  {status}",
        "log_status_with_fails_fmt": "  {status}  ({n} check(s) failed)",
        "log_error_fmt": "  Error: {err}",
        "log_done_fmt": "Validation finished: {ok} OK, {fail} FAIL, {err} error(s), {total} total.",
        "log_cancel_requested": "Cancel requested. The worker will stop after the current file.",
        "log_cancelled": "Validation cancelled by user.",
        "log_combined_written_fmt": "Report written: {path}",
        "log_write_failed_fmt": "  could not write: {err}",
        "log_detail_fmt": "--- Detail: {name} ---",
        "log_not_validated_yet": "(not validated yet)",
        "log_error_during_fmt": "Error during validation: {err}",
        "label_progress_fmt": "Processing: {done} / {total}",
        "label_done_fmt": "Done: {ok} OK, {fail} FAIL, {err} error(s) / {total}",
        "lang_dialog_title": "Select language / Selecteer taal / Sélectionnez la langue",
    },
}


# --- Settings ------------------------------------------------------------


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_settings(settings: dict) -> None:
    try:
        SETTINGS_PATH.write_text(
            json.dumps(settings, indent=2), encoding="utf-8",
        )
    except OSError:
        # Settings persistence is best-effort; ignore failures.
        pass


def translate(lang: str, key: str, **kw) -> str:
    """Look up a translation key in the given language, falling back to English.

    Module-level so the worker thread can produce log strings without
    touching any Tk state.
    """
    s = LANGUAGES.get(lang, LANGUAGES[DEFAULT_LANG]).get(key)
    if s is None:
        s = LANGUAGES[DEFAULT_LANG].get(key, key)
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError):
            return s
    return s


# --- Data ----------------------------------------------------------------


@dataclass
class FileEntry:
    """One row in the file list / results table."""

    path: Path
    status_code: str = "waiting"  # waiting / processing / ok / fail / error
    fail_count: int = 0
    result: ValidationResult | None = None
    error_message: str = ""


# --- Worker / message types ----------------------------------------------


@dataclass
class _MsgLog:
    text: str


@dataclass
class _MsgStarted:
    path: Path


@dataclass
class _MsgFinished:
    path: Path
    result: ValidationResult | None
    error_message: str = ""


@dataclass
class _MsgDone:
    pass


# --- GUI -----------------------------------------------------------------


class ValidatorGUI(tk.Tk):

    def __init__(self) -> None:
        super().__init__()

        # Application state
        self.settings = load_settings()
        saved_lang = self.settings.get("language") or ""
        self.lang: str = saved_lang if saved_lang in LANGUAGES else DEFAULT_LANG
        self._needs_lang_picker = saved_lang not in LANGUAGES
        self.entries: dict[Path, FileEntry] = {}
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self._poll_pending = True  # gate for the after()-loop
        # Cooperative cancellation flag, set from the main thread by
        # _on_cancel and polled by the worker between files.
        self._stop_flag = threading.Event()

        # Tk variables
        self.output_dir = tk.StringVar(value="")
        self.write_txt_var = tk.BooleanVar(value=True)
        self.write_csv_var = tk.BooleanVar(value=False)

        # Progress state, kept so we can re-render on language switch
        self._progress_done = 0
        self._progress_total = 0
        self._progress_kind = "idle"  # idle / running / done
        self._final_counts = (0, 0, 0, 0)  # ok, fail, err, total

        self.geometry("960x720")
        self.minsize(720, 540)

        self._build_ui()
        self._apply_language()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_queue)

        # First-run language picker AFTER the main UI is up and visible.
        if self._needs_lang_picker:
            self.after(50, self._show_language_picker)

    # --- Translation helper ----------------------------------------------

    def _t(self, key: str, **kw) -> str:
        """Translate via the current UI language. Main-thread only;
        worker code uses the module-level translate()."""
        return translate(self.lang, key, **kw)

    # --- First-run language picker ---------------------------------------

    def _show_language_picker(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Select language / Selecteer taal / Sélectionnez la langue")
        dialog.resizable(False, False)
        try:
            dialog.transient(self)
        except tk.TclError:
            pass

        intro = (
            "Kies een taal voor de interface.\n"
            "Choose the interface language.\n"
            "Choisissez la langue de l'interface."
        )
        ttk.Label(dialog, text=intro, padding=(16, 12)).pack(anchor="w")

        def pick(code: str) -> None:
            self.lang = code
            self.settings["language"] = code
            save_settings(self.settings)
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
            self._apply_language()

        btn_frame = ttk.Frame(dialog, padding=(16, 8, 16, 16))
        btn_frame.pack(fill="x")
        for code in ("nl", "fr", "en"):
            ttk.Button(
                btn_frame, text=LANGUAGES[code]["lang_name"], width=18,
                command=lambda c=code: pick(c),
            ).pack(pady=3, fill="x")

        dialog.update_idletasks()
        w = dialog.winfo_reqwidth()
        h = dialog.winfo_reqheight()
        rx = self.winfo_rootx()
        ry = self.winfo_rooty()
        rw = self.winfo_width() or 960
        rh = self.winfo_height() or 720
        dialog.geometry(f"+{rx + (rw - w) // 2}+{ry + (rh - h) // 2}")

        dialog.lift()
        dialog.focus_force()
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

    # --- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        self._build_menubar()

        # Top toolbar
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(99, weight=1)

        self.btn_add_file = ttk.Button(toolbar, command=self._on_add_file)
        self.btn_add_file.grid(row=0, column=0, padx=(0, 4))
        self.btn_add_folder = ttk.Button(toolbar, command=self._on_add_folder)
        self.btn_add_folder.grid(row=0, column=1, padx=4)
        self.btn_remove_selected = ttk.Button(
            toolbar, command=self._on_remove_selected,
        )
        self.btn_remove_selected.grid(row=0, column=2, padx=4)
        self.btn_clear = ttk.Button(toolbar, command=self._on_clear)
        self.btn_clear.grid(row=0, column=3, padx=4)

        # Results table
        table_frame = ttk.Frame(self, padding=(8, 0, 8, 0))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        cols = ("status", "fails", "format", "path")
        self.tree = ttk.Treeview(
            table_frame, columns=cols, show="headings", height=12,
        )
        self.tree.column("status", width=110, anchor="w", stretch=False)
        self.tree.column("fails", width=70, anchor="center", stretch=False)
        self.tree.column("format", width=80, anchor="center", stretch=False)
        self.tree.column("path", width=600, anchor="w", stretch=True)
        self.tree.tag_configure("ok", foreground="#107a3a")
        self.tree.tag_configure("fail", foreground="#b3261e")
        self.tree.tag_configure("error", foreground="#7a4d10")

        ysb = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        # Delete key (Backspace on macOS) removes the selected rows.
        self.tree.bind("<Delete>", lambda e: self._on_remove_selected())
        self.tree.bind("<BackSpace>", lambda e: self._on_remove_selected())

        # Output-folder chooser (mandatory)
        self.out_frame = ttk.LabelFrame(self, padding=(8, 6))
        self.out_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(8, 4))
        self.out_frame.columnconfigure(0, weight=1)

        self.out_entry = ttk.Entry(self.out_frame, textvariable=self.output_dir)
        self.out_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.out_browse_btn = ttk.Button(
            self.out_frame, command=self._on_browse_output,
        )
        self.out_browse_btn.grid(row=0, column=1, sticky="w")

        # Per-file format chooser
        self.fmt_frame = ttk.LabelFrame(self, padding=(8, 6))
        self.fmt_frame.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 4))
        self.cb_write_txt = ttk.Checkbutton(
            self.fmt_frame, variable=self.write_txt_var,
        )
        self.cb_write_txt.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.cb_write_csv = ttk.Checkbutton(
            self.fmt_frame, variable=self.write_csv_var,
        )
        self.cb_write_csv.grid(row=0, column=1, sticky="w")

        # Action row
        action_frame = ttk.Frame(self, padding=(8, 4))
        action_frame.grid(row=4, column=0, sticky="ew")
        action_frame.columnconfigure(99, weight=1)

        self.validate_btn = ttk.Button(action_frame, command=self._on_validate)
        self.validate_btn.grid(row=0, column=0, padx=(0, 4))
        self.cancel_btn = ttk.Button(
            action_frame, command=self._on_cancel, state="disabled",
        )
        self.cancel_btn.grid(row=0, column=1, padx=4)
        self.status_label = ttk.Label(action_frame, text="")
        self.status_label.grid(row=0, column=99, sticky="e")

        # Log panel
        self.log_frame = ttk.LabelFrame(self, padding=(8, 4))
        self.log_frame.grid(row=5, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.log_frame.rowconfigure(0, weight=1)
        self.log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            self.log_frame, height=10, wrap="none",
            state="disabled", font=("monospace", 9),
        )
        log_ysb = ttk.Scrollbar(
            self.log_frame, orient="vertical", command=self.log_text.yview,
        )
        log_xsb = ttk.Scrollbar(
            self.log_frame, orient="horizontal", command=self.log_text.xview,
        )
        self.log_text.configure(
            yscrollcommand=log_ysb.set, xscrollcommand=log_xsb.set,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_ysb.grid(row=0, column=1, sticky="ns")
        log_xsb.grid(row=1, column=0, sticky="ew")

        # Top-level grid weights
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(5, weight=2)

    def _build_menubar(self) -> None:
        old = getattr(self, "_menubar", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass

        menubar = tk.Menu(self)
        self.options_menu = tk.Menu(menubar, tearoff=False)
        self.language_menu = tk.Menu(self.options_menu, tearoff=False)
        for code in ("nl", "fr", "en"):
            self.language_menu.add_command(
                label=LANGUAGES[code]["lang_name"],
                command=lambda c=code: self._on_change_language(c),
            )
        self.options_menu.add_cascade(
            menu=self.language_menu, label=self._t("menu_language"),
        )
        menubar.add_cascade(
            menu=self.options_menu, label=self._t("menu_options"),
        )
        self._menubar = menubar
        self.config(menu=menubar)

    # --- Language switching ----------------------------------------------

    def _apply_language(self) -> None:
        self.title(self._t("title"))
        self._build_menubar()

        self.btn_add_file.config(text=self._t("btn_add_file"))
        self.btn_add_folder.config(text=self._t("btn_add_folder"))
        self.btn_remove_selected.config(text=self._t("btn_remove_selected"))
        self.btn_clear.config(text=self._t("btn_clear"))

        self.tree.heading("status", text=self._t("col_status"))
        self.tree.heading("fails", text=self._t("col_fails"))
        self.tree.heading("format", text=self._t("col_format"))
        self.tree.heading("path", text=self._t("col_path"))

        self.out_frame.config(text=self._t("out_label"))
        self.out_browse_btn.config(text=self._t("btn_browse"))

        self.fmt_frame.config(text=self._t("per_file_label"))
        self.cb_write_txt.config(text=self._t("write_txt"))
        self.cb_write_csv.config(text=self._t("write_csv"))

        self.validate_btn.config(text=self._t("btn_validate"))
        self.cancel_btn.config(text=self._t("btn_cancel"))

        self.log_frame.config(text=self._t("log_label"))

        for path in self.entries:
            self._update_row(path)

        self._refresh_status_label()

    def _on_change_language(self, code: str) -> None:
        if code == self.lang or code not in LANGUAGES:
            return
        self.lang = code
        self.settings["language"] = code
        save_settings(self.settings)
        self._apply_language()

    # --- Status / progress rendering -------------------------------------

    def _refresh_status_label(self) -> None:
        if self._progress_kind == "running":
            self.status_label.config(text=self._t(
                "label_progress_fmt",
                done=self._progress_done, total=self._progress_total,
            ))
        elif self._progress_kind == "done":
            ok, fail, err, total = self._final_counts
            self.status_label.config(text=self._t(
                "label_done_fmt", ok=ok, fail=fail, err=err, total=total,
            ))
        else:
            self.status_label.config(text="")

    def _status_display(self, code: str) -> str:
        return self._t(f"status_{code}")

    # --- UI events --------------------------------------------------------

    def _on_add_file(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self,
            title=self._t("dlg_pick_files"),
            filetypes=[
                (self._t("filter_obj"), "*.obj"),
                (self._t("filter_all"), "*.*"),
            ],
        )
        added = 0
        for p in paths:
            if self._add_entry(Path(p)):
                added += 1
        if added:
            self._log(self._t("log_added_fmt", n=added))

    def _on_add_folder(self) -> None:
        folder = filedialog.askdirectory(
            parent=self,
            title=self._t("dlg_pick_folder"),
            mustexist=True,
        )
        if not folder:
            return
        root = Path(folder)
        added = 0
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                if self._add_entry(p):
                    added += 1
        self._log(self._t("log_scanned_fmt", root=root, n=added))

    def _add_entry(self, path: Path) -> bool:
        path = path.resolve()
        if path in self.entries:
            return False
        entry = FileEntry(path=path)
        self.entries[path] = entry
        fmt = path.suffix.lower().lstrip(".").upper() or "?"
        self.tree.insert(
            "", "end", iid=str(path),
            values=(self._status_display(entry.status_code), "", fmt, str(path)),
        )
        return True

    def _on_clear(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(
                self._t("msg_running_title"),
                self._t("msg_running"),
            )
            return
        self.entries.clear()
        self.tree.delete(*self.tree.get_children())
        self._progress_kind = "idle"
        self._refresh_status_label()
        self._log(self._t("log_cleared"))

    def _on_remove_selected(self) -> None:
        """Remove the currently selected rows from the file list.

        Refused while a validation is running, to avoid the worker
        operating on a path that has been removed mid-flight.
        """
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(
                self._t("msg_running_title"),
                self._t("msg_running"),
            )
            return
        sel = self.tree.selection()
        if not sel:
            return
        for iid in sel:
            path = Path(iid)
            self.entries.pop(path, None)
            try:
                self.tree.delete(iid)
            except tk.TclError:
                pass
        self._log(self._t("log_removed_fmt", n=len(sel)))
        if not self.entries:
            self._progress_kind = "idle"
            self._refresh_status_label()

    def _on_browse_output(self) -> None:
        folder = filedialog.askdirectory(
            parent=self,
            title=self._t("dlg_pick_output"),
            mustexist=True,
        )
        if folder:
            self.output_dir.set(folder)

    def _on_row_select(self, event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        path = Path(sel[0])
        entry = self.entries.get(path)
        if not entry:
            return
        self._log(self._t("log_detail_fmt", name=path.name))
        if entry.result is not None:
            for line in format_result_lines(entry.result):
                self._log(line)
        elif entry.error_message:
            self._log(self._t("log_error_during_fmt", err=entry.error_message))
        else:
            self._log(self._t("log_not_validated_yet"))
        self._log("")

    def _on_validate(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.entries:
            messagebox.showinfo(
                self._t("msg_no_files_title"),
                self._t("msg_no_files"),
            )
            return

        # Snapshot all Tk-vars on the main thread before spawning the
        # worker. Tk-vars must NOT be touched from another thread (Tk
        # is single-threaded).
        output_dir_str = self.output_dir.get().strip()
        write_txt = self.write_txt_var.get()
        write_csv = self.write_csv_var.get()
        lang_snapshot = self.lang

        if not write_txt and not write_csv:
            messagebox.showerror(
                self._t("msg_no_format_title"),
                self._t("msg_no_format"),
            )
            return

        # Output folder is mandatory: there is no per-file mode any
        # more, so all combined reports need a target directory.
        if not output_dir_str:
            messagebox.showerror(
                self._t("msg_no_outdir_title"),
                self._t("msg_no_outdir"),
            )
            return
        output_dir = Path(output_dir_str)
        if not output_dir.is_dir():
            messagebox.showerror(
                self._t("msg_bad_outdir_title"),
                self._t("msg_bad_outdir_fmt", dir=output_dir_str),
            )
            return

        # Reset table state
        for path, entry in self.entries.items():
            entry.status_code = "waiting"
            entry.fail_count = 0
            entry.result = None
            entry.error_message = ""
            self._update_row(path)

        self.validate_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self._stop_flag.clear()
        files = list(self.entries.keys())
        self._progress_kind = "running"
        self._progress_done = 0
        self._progress_total = len(files)
        self._refresh_status_label()
        self._log(self._t("log_start_fmt", n=len(files)))

        self.worker = threading.Thread(
            target=self._validation_worker,
            args=(
                files, output_dir,
                write_txt, write_csv, lang_snapshot,
            ),
            daemon=True,
        )
        self.worker.start()

    def _on_cancel(self) -> None:
        """Set the stop flag; the worker checks it between files and stops."""
        if self.worker and self.worker.is_alive():
            self._stop_flag.set()
            self.cancel_btn.config(state="disabled")
            self._log(self._t("log_cancel_requested"))

    # --- Worker / queue ---------------------------------------------------

    def _validation_worker(
        self,
        files: list[Path],
        output_dir: Path,
        write_txt: bool,
        write_csv: bool,
        lang_snapshot: str,
    ) -> None:
        """Background worker. Receives all needed state as arguments
        and never touches Tk variables, widgets, or self.lang directly.
        """

        def t(key: str, **kw) -> str:
            return translate(lang_snapshot, key, **kw)

        cancelled = False
        # Collect successful results so we can write the combined
        # text/csv reports at the end of the run.
        collected: list[ValidationResult] = []

        for path in files:
            # Cooperative cancellation: between files only. The current
            # file is allowed to finish naturally so its data is
            # included in the combined report.
            if self._stop_flag.is_set():
                cancelled = True
                break

            self.queue.put(_MsgStarted(path))
            self.queue.put(_MsgLog(t("log_validating_fmt", name=path.name)))
            try:
                if not path.is_file():
                    self.queue.put(_MsgFinished(
                        path=path, result=None,
                        error_message="File not found",
                    ))
                    continue

                # Stream parser progress to the log so large files do
                # not appear stuck during their multi-second parse.
                def progress(msg: str) -> None:
                    self.queue.put(_MsgLog(f"  {msg}"))

                result = validate_obj_path(path, progress_callback=progress)
                collected.append(result)
                self.queue.put(_MsgFinished(path=path, result=result))
            except Exception as e:
                self.queue.put(_MsgFinished(
                    path=path, result=None,
                    error_message=f"{type(e).__name__}: {e}",
                ))

        # End of run: one combined report per requested format.
        if collected:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            if write_txt:
                self._write_combined(
                    collected, output_dir / f"validation_batch_{ts}.txt",
                    write_combined_text_report, lang_snapshot,
                )
            if write_csv:
                self._write_combined(
                    collected, output_dir / f"validation_batch_{ts}.csv",
                    write_combined_csv_report, lang_snapshot,
                )

        if cancelled:
            self.queue.put(_MsgLog(t("log_cancelled")))
        self.queue.put(_MsgDone())

    def _poll_queue(self) -> None:
        if not self._poll_pending:
            return
        try:
            while True:
                msg = self.queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        try:
            self.after(100, self._poll_queue)
        except tk.TclError:
            # Window has been destroyed; stop scheduling.
            self._poll_pending = False

    def _handle_message(self, msg) -> None:
        if isinstance(msg, _MsgLog):
            self._log(msg.text)
            return
        if isinstance(msg, _MsgStarted):
            entry = self.entries.get(msg.path)
            if entry:
                entry.status_code = "processing"
                self._update_row(msg.path)
            return
        if isinstance(msg, _MsgFinished):
            entry = self.entries.get(msg.path)
            if not entry:
                return
            if msg.result is not None:
                entry.result = msg.result
                entry.fail_count = msg.result.error_count
                entry.status_code = "ok" if msg.result.overall_ok else "fail"
                status_disp = self._status_display(entry.status_code)
                if entry.fail_count:
                    self._log(self._t(
                        "log_status_with_fails_fmt",
                        status=status_disp, n=entry.fail_count,
                    ))
                else:
                    self._log(self._t("log_status_fmt", status=status_disp))
            else:
                entry.status_code = "error"
                entry.error_message = msg.error_message
                self._log(self._t("log_error_fmt", err=msg.error_message))
            self._update_row(msg.path)
            self._update_progress()
            return
        if isinstance(msg, _MsgDone):
            self.validate_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")
            ok = sum(1 for e in self.entries.values() if e.status_code == "ok")
            fail = sum(1 for e in self.entries.values() if e.status_code == "fail")
            err = sum(1 for e in self.entries.values() if e.status_code == "error")
            total = len(self.entries)
            self._final_counts = (ok, fail, err, total)
            self._progress_kind = "done"
            self._refresh_status_label()
            self._log(self._t(
                "log_done_fmt",
                ok=ok, fail=fail, err=err, total=total,
            ))

    def _update_progress(self) -> None:
        done = sum(
            1 for e in self.entries.values()
            if e.status_code not in ("waiting", "processing")
        )
        self._progress_done = done
        self._progress_total = len(self.entries)
        self._refresh_status_label()

    def _update_row(self, path: Path) -> None:
        entry = self.entries.get(path)
        if not entry:
            return
        fmt = entry.path.suffix.lower().lstrip(".").upper() or "?"
        fails = (
            "" if entry.status_code in ("waiting", "processing")
            else str(entry.fail_count)
        )
        tag = ""
        if entry.status_code == "ok":
            tag = "ok"
        elif entry.status_code == "fail":
            tag = "fail"
        elif entry.status_code == "error":
            tag = "error"
        self.tree.item(
            str(path),
            values=(
                self._status_display(entry.status_code),
                fails, fmt, str(path),
            ),
            tags=(tag,) if tag else (),
        )

    def _on_close(self) -> None:
        """WM_DELETE_WINDOW handler: warn if a worker is still running."""
        if self.worker and self.worker.is_alive():
            ok = messagebox.askokcancel(
                self._t("msg_running_title"),
                self._t("msg_running"),
            )
            if not ok:
                return
        self._poll_pending = False
        self.destroy()

    # --- Output helpers (called from worker thread) ----------------------

    def _write_combined(
        self,
        results: list[ValidationResult],
        out_path: Path,
        writer,
        lang_snapshot: str,
    ) -> None:
        """Write a combined report (txt or csv) by delegating to the
        provided writer function. Worker-thread safe.
        """
        try:
            writer(results, out_path)
            self.queue.put(_MsgLog(translate(
                lang_snapshot, "log_combined_written_fmt", path=out_path,
            )))
        except OSError as e:
            self.queue.put(_MsgLog(translate(
                lang_snapshot, "log_write_failed_fmt", err=e,
            )))

    # --- Logging ----------------------------------------------------------

    def _log(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{ts}] {text}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")


def main() -> int:
    try:
        app = ValidatorGUI()
    except tk.TclError as e:
        msg = (
            f"Cannot open a Tk window: {e}\n"
            "This GUI does not work on headless systems. "
            "Use the CLI: python validate_obj_refs.py PATH"
        )
        print(msg, file=sys.stderr)
        return 2
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
