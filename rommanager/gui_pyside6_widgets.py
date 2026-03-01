from __future__ import annotations

from typing import Optional

import os

from PySide6 import QtCore, QtGui, QtWidgets

from . import i18n as _i18n


LANG_EN = getattr(_i18n, "LANG_EN", "en")
LANG_PT_BR = getattr(_i18n, "LANG_PT_BR", "pt-BR")


def _tr(key: str, **kwargs) -> str:
    func = getattr(_i18n, "tr", None)
    if callable(func):
        return func(key, **kwargs)
    return key


COLORS = {
    "base": "#1E1E1E",
    "mantle": "#151515",
    "surface0": "#2D2D2D",
    "surface1": "#2D2D2D",
    "text": "#E0E0E0",
    "subtext0": "#A0A0A0",
    "accent": "#39FF14",
    "accent_dark": "#1A1A1A",
    "red": "#FF00FF",
    "yellow": "#F9E2AF",
    "green": "#39FF14",
    "blue": "#89B4FA",
    "peach": "#FAB387",
}


def apply_global_style(app: QtWidgets.QApplication) -> None:
    app.setStyle("Fusion")
    app.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(COLORS["base"]))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(COLORS["text"]))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(COLORS["surface0"]))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(COLORS["mantle"]))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor(COLORS["text"]))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(COLORS["surface1"]))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(COLORS["text"]))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(COLORS["accent"]))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(COLORS["accent_dark"]))
    app.setPalette(palette)

    base_font = QtGui.QFont("Segoe UI")
    base_font.setStyleHint(QtGui.QFont.StyleHint.SansSerif)
    base_font.setFixedPitch(False)
    base_font.setStyleStrategy(QtGui.QFont.StyleStrategy.PreferAntialias)
    base_font.setHintingPreference(QtGui.QFont.HintingPreference.PreferFullHinting)
    base_font.setPixelSize(13)
    app.setFont(base_font)

    style_path = os.path.join(os.path.dirname(__file__), "gui_pyside6_style.qss")
    if os.path.isfile(style_path):
        with open(style_path, "r", encoding="utf-8") as handle:
            app.setStyleSheet(handle.read())


def section_title(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    font = label.font()
    font.setPixelSize(18)
    label.setFont(font)
    label.setObjectName("H2")
    label.setWordWrap(True)
    return label


def card_widget() -> QtWidgets.QFrame:
    frame = QtWidgets.QFrame()
    return frame


def subtle_label(text: str, size: int = 12) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    font = label.font()
    font.setPixelSize(size)
    label.setFont(font)
    label.setObjectName("Subtle")
    label.setWordWrap(True)
    return label


def headline(text: str, size: int = 32) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    font = label.font()
    font.setPixelSize(size)
    label.setFont(font)
    label.setObjectName("H1")
    label.setWordWrap(True)
    return label


def pick_file(parent: QtWidgets.QWidget, title: str, filter_text: str = "All files (*.*)") -> str:
    path, _ = QtWidgets.QFileDialog.getOpenFileName(parent, title, "", filter_text)
    return path or ""


def pick_dir(parent: QtWidgets.QWidget, title: str) -> str:
    return QtWidgets.QFileDialog.getExistingDirectory(parent, title) or ""


class EmptyState(QtWidgets.QFrame):
    def __init__(self, heading: str, subtext: str, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        icon = QtWidgets.QLabel("🗂")
        title = QtWidgets.QLabel(heading)
        subtitle = QtWidgets.QLabel(subtext)
        subtitle.setWordWrap(True)
        layout.addWidget(icon, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)


class StatCard(QtWidgets.QFrame):
    def __init__(self, label: str, value: str, accent: str, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setObjectName("stat_card")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        badge = QtWidgets.QLabel("●")
        badge.setObjectName("stat_badge")
        badge.setFixedSize(36, 36)
        badge.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        text_col = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel(label)
        value_label = QtWidgets.QLabel(value)
        text_col.addWidget(title)
        text_col.addWidget(value_label)
        layout.addWidget(badge)
        layout.addLayout(text_col)
