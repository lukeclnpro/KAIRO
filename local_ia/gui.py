"""Fenetre graphique qui pilote le meme CLI et le meme stockage que le terminal."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

BASE_DIR = Path(__file__).resolve().parents[1]
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECRET_PROMPT_RE = re.compile(
    r"(?i)(?:mot\s+de\s+passe[^:\n]{0,60}|(?:nouvelle\s+)?cl[eé]\s+api[^:\n]{0,60})\s*:\s*$"
)


class KairoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KAIRO · Console graphique")
        self.setMinimumSize(900, 600)
        self.resize(1220, 790)
        self._buffer = ""
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.started.connect(self._on_started)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_process_error)
        self._build_ui()
        self._apply_style()
        self._start_cli()

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("app")
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(22, 24, 18, 20)
        sidebar_layout.setSpacing(12)

        brand = QLabel("KAIRO")
        brand.setObjectName("brand")
        tagline = QLabel("IA LOCALE · CONSOLE")
        tagline.setObjectName("tagline")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(tagline)
        sidebar_layout.addSpacing(22)

        section = QLabel("ESPACE DE TRAVAIL")
        section.setObjectName("sectionLabel")
        sidebar_layout.addWidget(section)
        active = QLabel("◈   Invite de commande")
        active.setObjectName("activeNav")
        sidebar_layout.addWidget(active)
        sidebar_layout.addSpacing(16)

        linked = QLabel("LIEN ACTIF")
        linked.setObjectName("sectionLabel")
        sidebar_layout.addWidget(linked)
        link_info = QLabel("Même moteur que le terminal. Les conversations et la configuration restent partagées.")
        link_info.setObjectName("linkInfo")
        link_info.setWordWrap(True)
        sidebar_layout.addWidget(link_info)
        sidebar_layout.addStretch(1)

        self.start_button = QPushButton("Démarrer la console")
        self.start_button.setObjectName("secondaryButton")
        self.start_button.clicked.connect(self._start_cli)
        self.clear_button = QPushButton("Effacer l'affichage")
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self._clear_display)
        sidebar_layout.addWidget(self.start_button)
        sidebar_layout.addWidget(self.clear_button)
        version = self._read_version()
        version_label = QLabel(f"BÊTA {version}  ·  TERMINAL LIÉ")
        version_label.setObjectName("versionLabel")
        sidebar_layout.addSpacing(14)
        sidebar_layout.addWidget(version_label)
        layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(26, 22, 26, 22)
        content_layout.setSpacing(14)

        header = QHBoxLayout()
        heading_box = QVBoxLayout()
        title = QLabel("Console KAIRO")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Tous les menus et commandes du terminal, dans une fenêtre graphique.")
        subtitle.setObjectName("subtitle")
        heading_box.addWidget(title)
        heading_box.addWidget(subtitle)
        header.addLayout(heading_box)
        header.addStretch(1)
        self.status = QLabel("●  Démarrage")
        self.status.setObjectName("status")
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignVCenter)
        content_layout.addLayout(header)

        console_frame = QFrame()
        console_frame.setObjectName("consoleFrame")
        console_layout = QVBoxLayout(console_frame)
        console_layout.setContentsMargins(1, 1, 1, 1)
        self.output = QPlainTextEdit()
        self.output.setObjectName("terminalOutput")
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(QFont("Noto Sans Mono", 10))
        self.output.setPlaceholderText("La console KAIRO apparaîtra ici.")
        console_layout.addWidget(self.output)
        content_layout.addWidget(console_frame, stretch=1)

        self.prompt_hint = QLabel("En attente de la console…")
        self.prompt_hint.setObjectName("promptHint")
        content_layout.addWidget(self.prompt_hint)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        self.command_input = QLineEdit()
        self.command_input.setObjectName("commandInput")
        self.command_input.setPlaceholderText("Saisir un choix de menu ou une commande…")
        self.command_input.returnPressed.connect(self._send_input)
        self.send_button = QPushButton("Envoyer  ↵")
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self._send_input)
        input_row.addWidget(self.command_input, stretch=1)
        input_row.addWidget(self.send_button)
        content_layout.addLayout(input_row)
        layout.addWidget(content, stretch=1)

    @staticmethod
    def _read_version():
        try:
            import json

            data = json.loads((BASE_DIR / "version.json").read_text(encoding="utf-8"))
            return f"{data.get('version', '')}.{data.get('patch', '')}"
        except (OSError, ValueError):
            return "locale"

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget#app { background: #10191b; color: #e6efea; }
            QFrame#sidebar { background: #152326; border-right: 1px solid #2c3c3b; }
            QLabel#brand { color: #b5efc8; font-size: 27px; font-weight: 800; }
            QLabel#tagline, QLabel#sectionLabel { color: #849b91; font-size: 10px; font-weight: 700; }
            QLabel#sectionLabel { margin-top: 4px; }
            QLabel#activeNav { background: #203832; color: #c9f4d6; border-left: 3px solid #8cddb0; padding: 11px 10px; border-radius: 4px; font-weight: 700; }
            QLabel#linkInfo { color: #a9b9b1; line-height: 1.5; }
            QLabel#versionLabel { color: #71877f; font-size: 10px; }
            QLabel#pageTitle { color: #f1f5f1; font-size: 24px; font-weight: 700; }
            QLabel#subtitle { color: #93a69d; font-size: 12px; }
            QLabel#status { color: #a8e4b9; background: #1d3029; border: 1px solid #345745; border-radius: 8px; padding: 8px 11px; font-size: 11px; }
            QFrame#consoleFrame { background: #0a1113; border: 1px solid #2e4140; border-radius: 8px; }
            QPlainTextEdit#terminalOutput { background: transparent; color: #dae7df; border: 0; padding: 17px; selection-background-color: #355f4a; }
            QLabel#promptHint { color: #94aa9f; font-family: 'Noto Sans Mono'; font-size: 11px; }
            QLineEdit#commandInput { background: #192729; color: #eef6f0; border: 1px solid #38504a; border-radius: 7px; padding: 13px 14px; selection-background-color: #355f4a; }
            QPushButton { border-radius: 7px; padding: 11px 13px; font-weight: 700; }
            QPushButton#sendButton { background: #a5e8b9; color: #13231b; min-width: 102px; }
            QPushButton#sendButton:hover { background: #c0f2ce; }
            QPushButton#secondaryButton { background: #223331; color: #d2e3d9; border: 1px solid #344a43; text-align: left; }
            QPushButton#secondaryButton:hover { background: #2b4339; }
        """)

    def _start_cli(self):
        if self._process.state() != QProcess.ProcessState.NotRunning:
            return
        interpreter = Path(sys.executable)
        if os.name == "nt" and interpreter.name.lower() == "pythonw.exe":
            interpreter = interpreter.with_name("python.exe")
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("LOCAL_IA_GUI_CHILD", "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        self._process.setProcessEnvironment(environment)
        self._process.setWorkingDirectory(str(BASE_DIR))
        self._process.setProgram(str(interpreter))
        self._process.setArguments([str(BASE_DIR / "main.py"), "--gui-console"])
        self._buffer = ""
        self.status.setText("●  Connexion au moteur")
        self._process.start()

    def _on_started(self):
        self.status.setText("●  Console active")
        self.command_input.setFocus()

    def _on_finished(self, exit_code, _exit_status):
        self.status.setText(f"●  Console arrêtée ({exit_code})")
        self.prompt_hint.setText("Cliquez sur « Démarrer la console » pour relancer.")

    def _on_process_error(self, _error):
        self.status.setText("●  Impossible de démarrer")
        self._append_text("Impossible de lancer le processus CLI. Vérifiez Python et les dépendances du projet.\n")

    def _read_output(self):
        text = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if "\x1b[2J" in text or "\x1b[3J" in text:
            self._clear_display()
        text = _ANSI_RE.sub("", text).replace("\r", "")
        self._buffer += text
        self._consume_buffer()

    def _consume_buffer(self):
        secret_match = _SECRET_PROMPT_RE.search(self._buffer)
        if secret_match and "\n" not in self._buffer[secret_match.start():]:
            before = self._buffer[:secret_match.start()]
            if before:
                self._append_text(before)
            prompt = secret_match.group(0).strip()
            self._buffer = ""
            self.prompt_hint.setText("Saisie sensible · masquée")
            value, accepted = QInputDialog.getText(
                self,
                "Saisie sécurisée",
                prompt,
                QLineEdit.EchoMode.Password,
            )
            self._process.write(((value if accepted else "") + "\n").encode("utf-8"))
            self.prompt_hint.setText("En attente de la console…")
            return

        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._append_text(line + "\n")
        visible_prompt = self._buffer.strip()
        if visible_prompt:
            self.prompt_hint.setText(visible_prompt[-140:])

    def _append_text(self, text):
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def _send_input(self):
        if self._process.state() != QProcess.ProcessState.Running:
            self._start_cli()
            return
        value = self.command_input.text()
        if not value and not self._buffer:
            return
        prompt = self._buffer
        self._buffer = ""
        self.prompt_hint.setText("En attente de la console…")
        if prompt:
            self._append_text(prompt + value + "\n")
        elif value:
            self._append_text(f"› {value}\n")
        self.command_input.clear()
        self._process.write((value + "\n").encode("utf-8"))

    def _clear_display(self):
        self.output.clear()

    def closeEvent(self, event):
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.terminate()
            if not self._process.waitForFinished(1200):
                self._process.kill()
                self._process.waitForFinished(1200)
        event.accept()


def run_gui():
    from local_ia.gui_workspace import run_gui as run_workspace

    return run_workspace()
