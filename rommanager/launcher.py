"""Launcher window to choose which interface to run."""
import tkinter as tk
from tkinter import ttk
import sys
import webbrowser
import threading

from .web import run_server
from .gui import run_gui, GUI_AVAILABLE


def open_flet_mode(root):
    """Start the Flet desktop app."""
    root.destroy()
    try:
        from .gui_flet import run_flet_gui
        run_flet_gui()
    except ImportError as exc:
        print("Error: Flet interface is not available.")
        print("Install it with: pip install flet")
        print(f"Details: {exc}")
        sys.exit(1)

def open_web_mode(root):
    """Start web server and open browser"""
    root.destroy()
    print("Starting Web Interface...")
    # Open browser after a slight delay to ensure server is running
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    run_server()

def open_desktop_mode(root):
    """Start desktop GUI"""
    root.destroy()
    if GUI_AVAILABLE:
        run_gui()
    else:
        print("Error: Desktop GUI (tkinter) is not available.")
        sys.exit(1)


def open_cli_mode(root):
    """Show CLI usage/help in the current terminal."""
    root.destroy()
    print("Starting CLI mode...")
    from .cli import run_cli
    run_cli(['--help'])

def run_launcher():
    """Run the selection launcher"""
    if not GUI_AVAILABLE:
        print("Tkinter not available. Starting Web Interface automatically...")
        run_server()
        return

    root = tk.Tk()
    root.title("ROM Manager")
    root.geometry("460x340")
    root.resizable(False, False)
    
    # Center window
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - 460) // 2
    y = (screen_height - 340) // 2
    root.geometry(f"460x340+{x}+{y}")
    
    # Styles
    style = ttk.Style()
    style.configure('TButton', font=('Segoe UI', 11), padding=10)
    style.configure('Header.TLabel', font=('Segoe UI', 16, 'bold'))
    
    # Content
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Label(frame, text="ROM Collection Manager", 
             style='Header.TLabel').pack(pady=(10, 5))
    ttk.Label(frame, text="Choose your interface:",
             font=('Segoe UI', 10)).pack(pady=(0, 20))
    
    # Buttons
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill=tk.BOTH, expand=True)
    
    ttk.Button(btn_frame, text="✨ Flet Desktop\n(Moderno e responsivo)",
              command=lambda: open_flet_mode(root)).pack(fill=tk.X, pady=5)

    ttk.Button(btn_frame, text="🖥️ Tkinter Desktop\n(Simples, nativo)",
              command=lambda: open_desktop_mode(root)).pack(fill=tk.X, pady=5)

    ttk.Button(btn_frame, text="🌐 WebApp\n(Acesso pelo navegador)",
              command=lambda: open_web_mode(root)).pack(fill=tk.X, pady=5)

    ttk.Button(btn_frame, text="⌨️ CLI\n(Linha de comando no terminal)",
              command=lambda: open_cli_mode(root)).pack(fill=tk.X, pady=5)
    
    ttk.Label(frame, text="v1.0.0", font=('Segoe UI', 8), 
             foreground='gray').pack(side=tk.BOTTOM)
    
    root.mainloop()
