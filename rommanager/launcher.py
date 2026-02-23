"""Launcher window to choose which interface to run."""
import tkinter as tk
import sys
import webbrowser
import threading
import subprocess
import shutil
from pathlib import Path

from .web import run_server
from .gui import run_gui, GUI_AVAILABLE
from .monitor import attach_tk_click_monitor, install_tk_exception_bridge, monitor_action, setup_runtime_monitor
from . import i18n as _i18n
from .settings import load_settings, apply_runtime_settings
from . import __version__

LANG_EN = getattr(_i18n, "LANG_EN", "en")
LANG_PT_BR = getattr(_i18n, "LANG_PT_BR", "pt-BR")


def _tr(key, **kwargs):
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


def _set_language(lang):
    func = getattr(_i18n, "set_language", None)
    if callable(func):
        func(lang)


def _safe_get_language():
    """Return active language even if older i18n exports are missing."""
    getter = getattr(_i18n, "get_language", None)
    if callable(getter):
        return getter()
    return LANG_EN


def open_flet_mode(root):
    """Start the Flet desktop app."""
    monitor_action("launcher click: flet")
    root.destroy()
    try:
        from .gui_flet import run_flet_gui
        run_flet_gui()
    except ImportError as exc:
        print(_tr("error_flet_unavailable"))
        print(_tr("install_flet"))
        print(f"Details: {exc}")
        sys.exit(1)


def open_flutter_frontend_mode(root):
    """Start only the Flutter frontend (API is expected to be already running)."""
    monitor_action("launcher click: flutter_frontend")
    root.destroy()
    print(_tr("launcher_flutter_start"))

    flutter_project_root = Path(__file__).resolve().parent.parent
    flutter_path = shutil.which("flutter") or shutil.which("flutter.bat")
    if not flutter_path:
        print(_tr("error_flutter_unavailable"))
        print(_tr("install_flutter"))
        sys.exit(1)

    flutter_command = [
        flutter_path,
        "run",
        "-d",
        "chrome",
        "--dart-define",
        "R0MM_API_BASE=http://127.0.0.1:5000/api",
    ]
    try:
        subprocess.run(flutter_command, check=True, cwd=str(flutter_project_root))
    except subprocess.CalledProcessError as exc:
        print(_tr("error_flutter_failed"))
        print(f"Details: {exc}")
        sys.exit(exc.returncode or 1)


def open_pyside6_mode(root):
    """Start the PySide6 desktop app."""
    monitor_action("launcher click: pyside6")
    root.destroy()
    try:
        from .gui_pyside6 import run_pyside6_gui
        run_pyside6_gui()
    except ImportError as exc:
        print("PySide6 interface unavailable")
        print("Install with: pip install PySide6")
        print(f"Details: {exc}")
        sys.exit(1)


def open_web_mode(root):
    """Start web server and open browser"""
    monitor_action("launcher click: webapp")
    root.destroy()
    print(_tr("launcher_web_start"))
    # Open browser after a slight delay to ensure server is running
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    run_server(shutdown_on_idle=True)


def open_desktop_mode(root):
    """Start desktop GUI"""
    monitor_action("launcher click: tkinter")
    root.destroy()
    if GUI_AVAILABLE:
        run_gui()
    else:
        print(_tr("error_tk_unavailable"))
        sys.exit(1)


def open_cli_mode(root):
    """Show CLI usage/help in the current terminal."""
    monitor_action("launcher click: cli")
    root.destroy()
    print(_tr("launcher_cli_start"))
    from .cli import run_cli
    run_cli(['--help'])


def _change_language_launcher(root, lang):
    _set_language(lang)
    root.destroy()
    run_launcher()


def _build_option_card(parent, title, subtitle, command, accent_color):
    card = tk.Frame(
        parent,
        bg="#313244",
        highlightthickness=1,
        highlightbackground=accent_color,
        bd=0,
        height=82,
    )
    card.pack(fill=tk.X, pady=5)
    card.pack_propagate(False)

    title_btn = tk.Button(
        card,
        text=title,
        command=command,
        anchor="w",
        bg="#313244",
        fg="#cdd6f4",
        activebackground="#45475a",
        activeforeground="#ffffff",
        relief=tk.FLAT,
        bd=0,
        cursor="hand2",
        font=("Segoe UI", 11, "bold"),
        padx=14,
        pady=4,
    )
    title_btn.pack(fill=tk.X, pady=(8, 0))

    subtitle_lbl = tk.Label(
        card,
        text=subtitle,
        anchor="w",
        bg="#313244",
        fg="#a6adc8",
        font=("Segoe UI", 9),
        padx=16,
    )
    subtitle_lbl.pack(fill=tk.X, pady=(2, 8))

    card.bind("<Button-1>", lambda _e: command())
    subtitle_lbl.bind("<Button-1>", lambda _e: command())


def run_launcher():
    """Run the selection launcher"""
    apply_runtime_settings(load_settings())
    setup_runtime_monitor()
    if not GUI_AVAILABLE:
        print(_tr("launcher_tk_unavailable"))
        run_server(shutdown_on_idle=True)
        return

    root = tk.Tk()
    install_tk_exception_bridge(root)
    attach_tk_click_monitor(root)
    root.title(_tr("title_launcher"))
    monitor_action("launcher opened")

    width, height = 640, 650
    root.geometry(f"{width}x{height}")
    root.resizable(False, False)

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")

    lang_var = tk.StringVar(value=_safe_get_language())
    menubar = tk.Menu(root)
    lang_menu = tk.Menu(menubar, tearoff=0)
    lang_menu.add_radiobutton(
        label=_tr("language_english"),
        variable=lang_var,
        value=LANG_EN,
        command=lambda: _change_language_launcher(root, LANG_EN),
    )
    lang_menu.add_radiobutton(
        label=_tr("language_ptbr"),
        variable=lang_var,
        value=LANG_PT_BR,
        command=lambda: _change_language_launcher(root, LANG_PT_BR),
    )
    menubar.add_cascade(label=_tr("menu_language"), menu=lang_menu)
    root.config(menu=menubar)

    root.configure(bg="#11111b")

    frame = tk.Frame(root, bg="#1e1e2e", bd=0, highlightthickness=1, highlightbackground="#45475a")
    frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

    tk.Label(
        frame,
        text=_tr("title_main"),
        bg="#1e1e2e",
        fg="#cdd6f4",
        font=("Segoe UI", 28, "bold"),
    ).pack(pady=(20, 4))

    tk.Label(
        frame,
        text=_tr("choose_interface"),
        bg="#1e1e2e",
        fg="#a6adc8",
        font=("Segoe UI", 11),
    ).pack(pady=(0, 4))

    tk.Label(
        frame,
        text=_tr("launcher_brief"),
        bg="#1e1e2e",
        fg="#bac2de",
        font=("Segoe UI", 9),
    ).pack(pady=(0, 12))

    btn_frame = tk.Frame(frame, bg="#1e1e2e")
    btn_frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=(4, 10))

    options = [
        (_tr("launcher_flutter"), _tr("launcher_flutter_desc"), lambda: open_flutter_frontend_mode(root), "#b4befe"),
        (_tr("launcher_flet"), _tr("launcher_flet_desc"), lambda: open_flet_mode(root), "#cba6f7"),
        ("🧩 PySide6 Desktop", _tr("launcher_pyside_desc"), lambda: open_pyside6_mode(root), "#89b4fa"),
        (_tr("launcher_tk"), _tr("launcher_tk_desc"), lambda: open_desktop_mode(root), "#a6e3a1"),
        (_tr("launcher_web"), _tr("launcher_web_desc"), lambda: open_web_mode(root), "#fab387"),
        (_tr("launcher_cli"), _tr("launcher_cli_desc"), lambda: open_cli_mode(root), "#f9e2af"),
    ]

    for title, subtitle, command, accent in options:
        _build_option_card(btn_frame, title, subtitle, command, accent)

    tk.Label(
        frame,
        text=f"ver {__version__}",
        bg="#1e1e2e",
        fg="#6c7086",
        font=("Segoe UI", 9),
    ).pack(side=tk.BOTTOM, pady=(4, 14))

    root.mainloop()
