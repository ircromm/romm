"""Launcher window to choose which interface to run."""
import tkinter as tk
from tkinter import ttk
import sys
import webbrowser
import threading

from .web import run_server
from .gui import run_gui, GUI_AVAILABLE
from .monitor import install_tk_exception_bridge, monitor_action, setup_runtime_monitor
from . import i18n as _i18n
from .i18n import tr, set_language, LANG_EN, LANG_PT_BR


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
        print(tr("error_flet_unavailable"))
        print(tr("install_flet"))
        print(f"Details: {exc}")
        sys.exit(1)

def open_web_mode(root):
    """Start web server and open browser"""
    monitor_action("launcher click: webapp")
    root.destroy()
    print(tr("launcher_web_start"))
    # Open browser after a slight delay to ensure server is running
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    run_server()

def open_desktop_mode(root):
    """Start desktop GUI"""
    monitor_action("launcher click: tkinter")
    root.destroy()
    if GUI_AVAILABLE:
        run_gui()
    else:
        print(tr("error_tk_unavailable"))
        sys.exit(1)


def open_cli_mode(root):
    """Show CLI usage/help in the current terminal."""
    monitor_action("launcher click: cli")
    root.destroy()
    print(tr("launcher_cli_start"))
    from .cli import run_cli
    run_cli(['--help'])

def _change_language_launcher(root, lang):
    set_language(lang)
    root.destroy()
    run_launcher()


def run_launcher():
    """Run the selection launcher"""
    setup_runtime_monitor()
    if not GUI_AVAILABLE:
        print(tr("launcher_tk_unavailable"))
        run_server()
        return

    root = tk.Tk()
    install_tk_exception_bridge(root)
    root.title(tr("title_launcher"))
    monitor_action("launcher opened")
    root.geometry("460x340")
    root.resizable(False, False)
    
    # Center window
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - 460) // 2
    y = (screen_height - 340) // 2
    root.geometry(f"460x340+{x}+{y}")
    
    lang_var = tk.StringVar(value=_safe_get_language())

    menubar = tk.Menu(root)
    lang_menu = tk.Menu(menubar, tearoff=0)
    lang_menu.add_radiobutton(label=tr("language_english"), variable=lang_var, value=LANG_EN,
                              command=lambda: _change_language_launcher(root, LANG_EN))
    lang_menu.add_radiobutton(label=tr("language_ptbr"), variable=lang_var, value=LANG_PT_BR,
                              command=lambda: _change_language_launcher(root, LANG_PT_BR))
    menubar.add_cascade(label=tr("menu_language"), menu=lang_menu)
    root.config(menu=menubar)

    # Styles
    style = ttk.Style()
    style.configure('TButton', font=('Segoe UI', 11), padding=10)
    style.configure('Header.TLabel', font=('Segoe UI', 16, 'bold'))
    
    # Content
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(frame, text=tr("title_main"), 
             style='Header.TLabel').pack(pady=(10, 5))
    ttk.Label(frame, text=tr("choose_interface"),
             font=('Segoe UI', 10)).pack(pady=(0, 20))
    
    # Buttons
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Button(btn_frame, text=tr("launcher_flet"),
              command=lambda: open_flet_mode(root)).pack(fill=tk.X, pady=5)

    ttk.Button(btn_frame, text=tr("launcher_tk"),
              command=lambda: open_desktop_mode(root)).pack(fill=tk.X, pady=5)

    ttk.Button(btn_frame, text=tr("launcher_web"),
              command=lambda: open_web_mode(root)).pack(fill=tk.X, pady=5)

    ttk.Button(btn_frame, text=tr("launcher_cli"),
              command=lambda: open_cli_mode(root)).pack(fill=tk.X, pady=5)
    
    ttk.Label(frame, text="v1.0.0", font=('Segoe UI', 8), 
             foreground='gray').pack(side=tk.BOTTOM)
    
    root.mainloop()
