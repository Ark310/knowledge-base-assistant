# scraper/settings_dialog.py
"""Settings dialog: per-type output folders (Tickets / Knowledge Base),
browser mode toggle, and hidden portal credentials.  Output paths and browser
mode are persisted via app_settings; the password is stored in the OS keyring
via ticket_settings — never logged."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton,
    QVBoxLayout, QWidget,
)

import scraper.app_settings as app_settings
import scraper.ticket_settings as ticket_settings


class SettingsDialog(QDialog):
    """Modal settings editor: output folder rows + collapsible portal credentials."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # ── Output folders ────────────────────────────────────────────────────
        layout.addWidget(_section_label("Output Folders"))

        self.inp_tickets = self._folder_row(
            layout, "Tickets folder:", str(app_settings.tickets_dir())
        )
        self.inp_kb = self._folder_row(
            layout, "Knowledge Base folder:", str(app_settings.kb_dir())
        )

        # ── Browser mode ─────────────────────────────────────────────────────
        layout.addWidget(_section_label("Browser Mode"))

        mode_box = QGroupBox()
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setContentsMargins(8, 6, 8, 6)
        mode_layout.setSpacing(6)

        self._radio_light = QRadioButton(
            "Light — one window, many tabs (recommended)"
        )
        self._radio_multi = QRadioButton(
            "Multi-window — one Chrome per worker"
        )
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._radio_light)
        self._mode_group.addButton(self._radio_multi)

        mode_layout.addWidget(self._radio_light)
        mode_layout.addWidget(self._radio_multi)

        # Headless toggle — far lighter per tab; recommended for large batches (bug-111).
        self.chk_headless = QCheckBox(
            "Run browser hidden (headless) — faster & more stable for large batches"
        )
        self.chk_headless.setChecked(app_settings.headless())
        mode_layout.addWidget(self.chk_headless)

        layout.addWidget(mode_box)

        # Initialise from persisted setting (default = light)
        self.set_browser_mode_value(app_settings.browser_mode())

        # ── Portal credentials (collapsible) ─────────────────────────────────
        self._toggle_btn = QPushButton("▸  Portal credentials")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCheckable(False)
        self._toggle_btn.clicked.connect(self._toggle_creds)
        layout.addWidget(self._toggle_btn)

        self.cred_box = QWidget()
        self.cred_box.setVisible(False)
        cred_layout = QVBoxLayout(self.cred_box)
        cred_layout.setContentsMargins(0, 4, 0, 4)
        cred_layout.setSpacing(8)

        ts = ticket_settings.load()

        self.inp_url = QLineEdit(ts.get("portal_url", ""))
        self.inp_url.setPlaceholderText("Portal URL")
        cred_layout.addWidget(QLabel("Portal URL:"))
        cred_layout.addWidget(self.inp_url)

        self.inp_username = QLineEdit(ts.get("username", ""))
        self.inp_username.setPlaceholderText("Username / email")
        cred_layout.addWidget(QLabel("Username:"))
        cred_layout.addWidget(self.inp_username)

        self.inp_password = QLineEdit()
        self.inp_password.setEchoMode(QLineEdit.Password)
        self.inp_password.setPlaceholderText("Password (stored in OS keyring)")
        # Pre-fill from keyring so user can see there's a saved value
        _saved_pw = ticket_settings.load_password(ts.get("username", ""))
        if _saved_pw:
            self.inp_password.setText(_saved_pw)
        cred_layout.addWidget(QLabel("Password:"))
        cred_layout.addWidget(self.inp_password)

        btn_save_creds = QPushButton("Save credentials")
        btn_save_creds.clicked.connect(self._save_credentials)
        cred_layout.addWidget(btn_save_creds)

        layout.addWidget(self.cred_box)

        # ── Button row ────────────────────────────────────────────────────────
        bb = QDialogButtonBox()
        btn_save = bb.addButton("Save", QDialogButtonBox.AcceptRole)
        btn_save.setObjectName("PrimaryButton")
        btn_close = bb.addButton("Close", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._save_paths)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    # ── browser-mode helpers ──────────────────────────────────────────────────

    def set_browser_mode_value(self, m: str) -> None:
        """Select the radio button matching *m* ("light" or "multi"). Defaults to light."""
        if m == "multi":
            self._radio_multi.setChecked(True)
        else:
            self._radio_light.setChecked(True)

    def _browser_mode_value(self) -> str:
        """Return the currently selected browser mode string."""
        return "multi" if self._radio_multi.isChecked() else "light"

    # ── helpers ───────────────────────────────────────────────────────────────

    def _folder_row(self, parent_layout: QVBoxLayout, label: str, value: str) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(160)
        inp = QLineEdit(value)
        inp.setReadOnly(True)
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._browse(inp))
        row.addWidget(lbl)
        row.addWidget(inp, 1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return inp

    def _browse(self, inp: QLineEdit):
        chosen = QFileDialog.getExistingDirectory(self, "Select folder", inp.text())
        if chosen:
            inp.setText(chosen)

    def _toggle_creds(self):
        visible = not self.cred_box.isVisible()
        self.cred_box.setVisible(visible)
        self._toggle_btn.setText(("▾" if visible else "▸") + "  Portal credentials")
        self.adjustSize()

    def _save_credentials(self):
        """Write URL + username (never the password) to JSON; password to keyring only."""
        url = self.inp_url.text().strip()
        username = self.inp_username.text().strip()
        ticket_settings.save(url, username)
        pw = self.inp_password.text()  # never log this
        if pw and username:
            ok = ticket_settings.save_password(username, pw)
            if not ok:
                QMessageBox.warning(self, "Keyring unavailable",
                    "The password could not be saved to the OS keyring. "
                    "You will need to re-enter it each session.")
        QMessageBox.information(self, "Saved", "Portal credentials saved.")

    def _save(self):
        """Persist output folders + browser mode, then close the dialog."""
        app_settings.save(
            self.inp_tickets.text(),
            self.inp_kb.text(),
            browser_mode=self._browser_mode_value(),
        )
        app_settings.set_headless(self.chk_headless.isChecked())
        self.accept()

    def _save_paths(self):
        """Alias kept for back-compat (button box still connects here via accepted signal)."""
        self._save()


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight: 600; font-size: 11pt; margin-bottom: 2px;")
    return lbl
