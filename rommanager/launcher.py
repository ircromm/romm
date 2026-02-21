"""Unified launcher for selecting which ROM Manager interface to run."""

from __future__ import annotations

import shlex
from typing import Callable


def _run_flet() -> int:
    try:
        from .gui_flet import run_gui
    except ImportError as exc:
        print("Erro: interface Flet indisponível.")
        print(f"Detalhes: {exc}")
        return 1
    return run_gui()


def _run_tkinter() -> int:
    from .gui import GUI_AVAILABLE, run_gui

    if not GUI_AVAILABLE:
        print("Erro: interface Tkinter indisponível neste ambiente.")
        return 1
    return run_gui()


def _run_webapp() -> int:
    from .web import run_server

    run_server()
    return 0


def _run_cli_interactive() -> int:
    from .cli import run_cli

    print("\nModo CLI selecionado.")
    print("Digite os argumentos (ex: --dat nointro.dat --roms ./roms --output ./out)")
    print("Pressione Enter vazio para abrir apenas a ajuda.")

    raw_args = input("cli> ").strip()
    cli_args = shlex.split(raw_args) if raw_args else ["--help"]
    return run_cli(cli_args)


def _run_terminal_launcher() -> int:
    options: dict[str, tuple[str, Callable[[], int]]] = {
        "1": ("Flet", _run_flet),
        "2": ("Tkinter", _run_tkinter),
        "3": ("WebApp", _run_webapp),
        "4": ("CLI", _run_cli_interactive),
    }

    print("ROM Collection Manager")
    print("=" * 30)
    print("Escolha a interface para iniciar:")
    for key, (label, _) in options.items():
        print(f"  {key}. {label}")

    while True:
        choice = input("Seleção [1-4]: ").strip()
        if choice in options:
            label, runner = options[choice]
            print(f"\nIniciando: {label}\n")
            return runner()
        print("Opção inválida. Tente novamente.")


def run_launcher() -> int:
    """Run interface launcher and return process exit code."""
    try:
        return _run_terminal_launcher()
    except KeyboardInterrupt:
        print("\nInicialização cancelada pelo usuário.")
        return 130


__all__ = ["run_launcher"]
