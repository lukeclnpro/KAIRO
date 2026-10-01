"""Windows and Linux system tray launcher for LOCAL_IA."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
MAIN_SCRIPT = BASE_DIR / "main.py"
IS_WINDOWS = os.name == "nt"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
AUTOSTART_FILE = CONFIG_HOME / "autostart" / "local-ia-tray.desktop"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache"))
LOCK_FILE = RUNTIME_DIR / "local-ia-tray.lock"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_RUN_VALUE = "LOCAL_IA Tray"


def _desktop_quote(value: str | Path) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def install_autostart() -> None:
    if IS_WINDOWS:
        import winreg

        command = subprocess.list2cmdline(
            (_tray_python_executable(), str(MAIN_SCRIPT), "--tray")
        )
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            winreg.SetValueEx(key, WINDOWS_RUN_VALUE, 0, winreg.REG_SZ, command)
        return

    AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
    command = " ".join(
        (
            _desktop_quote(sys.executable),
            _desktop_quote(MAIN_SCRIPT),
            "--tray",
        )
    )
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=KAIRO Tray\n"
        "Comment=Ouvrir KAIRO depuis la zone de notification\n"
        f"Exec={command}\n"
        "Terminal=false\n"
        "X-KDE-autostart-after=panel\n"
    )

    if AUTOSTART_FILE.is_file() and AUTOSTART_FILE.read_text(encoding="utf-8") == content:
        return

    temporary_file = AUTOSTART_FILE.with_suffix(".desktop.tmp")
    temporary_file.write_text(content, encoding="utf-8")
    temporary_file.chmod(0o755)
    temporary_file.replace(AUTOSTART_FILE)


def disable_autostart() -> None:
    if IS_WINDOWS:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                WINDOWS_RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, WINDOWS_RUN_VALUE)
        except FileNotFoundError:
            pass
        return

    AUTOSTART_FILE.unlink(missing_ok=True)


def _tray_python_executable() -> str:
    if IS_WINDOWS:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            return str(pythonw)
    return sys.executable


def _console_python_executable() -> str:
    if IS_WINDOWS and Path(sys.executable).name.lower() == "pythonw.exe":
        python = Path(sys.executable).with_name("python.exe")
        if python.is_file():
            return str(python)
    return sys.executable


def _process_options(*, hide_window: bool = False, new_console: bool = False) -> dict:
    if IS_WINDOWS:
        creation_flags = 0
        if hide_window:
            creation_flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if new_console:
            creation_flags |= getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        return {"creationflags": creation_flags}
    return {"start_new_session": True}


def start_tray() -> None:
    install_autostart()
    subprocess.Popen(
        [_tray_python_executable(), str(MAIN_SCRIPT), "--tray"],
        cwd=BASE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_process_options(hide_window=True),
    )


def launch_main() -> None:
    if IS_WINDOWS:
        subprocess.Popen(
            [_console_python_executable(), str(MAIN_SCRIPT)],
            cwd=BASE_DIR,
            **_process_options(new_console=True),
        )
        return

    terminal = shutil.which("konsole") or shutil.which("x-terminal-emulator")
    if terminal is None:
        raise FileNotFoundError("Konsole ou x-terminal-emulator est introuvable.")

    command = [terminal]
    if Path(terminal).name == "konsole":
        command.append("--separate")
    command.extend(("-e", sys.executable, str(MAIN_SCRIPT)))
    subprocess.Popen(command, cwd=BASE_DIR, **_process_options())


def launch_gui() -> None:
    subprocess.Popen(
        [_tray_python_executable(), str(MAIN_SCRIPT), "--gui"],
        cwd=BASE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_process_options(hide_window=True),
    )


def _create_icon():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#17332d"))
    painter.drawRoundedRect(2, 2, 60, 60, 15, 15)
    painter.setPen(QColor("#9ef0c1"))
    painter.setFont(QFont("Sans Serif", 21, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "IA")
    painter.end()
    return QIcon(pixmap)


def run_tray() -> int:
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(LOCK_FILE))
    if not lock.tryLock(0):
        return 0

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 1

    tray = QSystemTrayIcon(_create_icon())
    tray.setToolTip("KAIRO · cliquer pour ouvrir l'interface graphique")

    menu = QMenu()
    open_action = menu.addAction("Ouvrir l'interface graphique")
    terminal_action = menu.addAction("Ouvrir dans le terminal")

    def open_application() -> None:
        try:
            launch_gui()
        except OSError as error:
            tray.showMessage(
                "KAIRO",
                str(error),
                QSystemTrayIcon.MessageIcon.Warning,
            )

    open_action.triggered.connect(open_application)
    terminal_action.triggered.connect(launch_main)
    menu.addSeparator()

    def disable_tray() -> None:
        disable_autostart()
        app.quit()

    disable_action = menu.addAction("Désactiver l’icône au démarrage")
    disable_action.triggered.connect(disable_tray)
    tray.setContextMenu(menu)

    def handle_activation(reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            open_application()

    tray.activated.connect(handle_activation)
    tray.show()
    return app.exec()