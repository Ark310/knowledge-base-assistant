# scraper/theme.py
"""Contoso brand theme for the v4 scraper — palette + app-wide QSS, ported from the
KB Chatbot (Dev/kb_chatbot/gui.py). Import-light (PySide6 + stdlib only) so the splash
paints before any heavy import."""
from __future__ import annotations
import sys
from pathlib import Path

PALETTE = {
    "brand":      "#51639e",
    "brand_deep": "#3f4f82",
    "warm":       "#de9b6f",
    "bg":         "#eef1f7",
    "surface":    "#ffffff",
    "surface_2":  "#f6f8fc",
    "border":     "#dfe4ee",
    "text":       "#1e2536",
    "muted":      "#6b7480",
}
FONT_STACK = "'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"

def asset_path(name: str) -> Path | None:
    base = Path(sys._MEIPASS) / "assets" if getattr(sys, "frozen", False) else Path(__file__).parent.parent / "assets"
    p = base / name
    return p if p.exists() else None

def asset_file_url(name: str) -> str | None:
    p = asset_path(name)
    return p.resolve().as_uri() if p else None

def app_stylesheet() -> str:
    P = PALETTE
    return f"""
    QWidget {{ background: {P['bg']}; color: {P['text']}; font-family: {FONT_STACK}; font-size: 13px; }}
    QTabWidget::pane {{ border: 1px solid {P['border']}; background: {P['surface']}; }}
    QTabBar::tab {{ background: {P['surface_2']}; color: {P['muted']}; padding: 8px 16px; border: 0; }}
    QTabBar::tab:selected {{ color: {P['brand']}; border-bottom: 2px solid {P['brand']}; background: {P['surface']}; }}
    QGroupBox {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 8px; margin-top: 8px; padding: 8px; }}
    QPlainTextEdit, QLineEdit, QTableWidget {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 6px; }}
    QHeaderView::section {{ background: {P['surface_2']}; color: {P['muted']}; border: 0; padding: 6px; }}
    QPushButton {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 6px; padding: 6px 12px; }}
    QPushButton:hover {{ border-color: {P['brand']}; }}
    QPushButton#PrimaryButton {{ background: {P['brand']}; color: white; border: 0; font-weight: bold; }}
    QPushButton#PrimaryButton:hover {{ background: {P['brand_deep']}; }}
    QProgressBar {{ border: 0; background: #e4e8f2; border-radius: 6px; height: 10px; }}
    QProgressBar::chunk {{ background: {P['brand']}; border-radius: 6px; }}
    """
