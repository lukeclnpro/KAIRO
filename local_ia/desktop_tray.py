"""Windows and Linux system tray launcher for LOCAL_IA."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
MAIN_SCRIPT = BASE_DIR / "main.py"
SLEEP_SCRIPT = BASE_DIR / "sleep.py"
IS_WINDOWS = os.name == "nt"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
AUTOSTART_FILE = CONFIG_HOME / "autostart" / "kairo-sleep.desktop"
LEGACY_AUTOSTART_FILE = CONFIG_HOME / "autostart" / "local-ia-tray.desktop"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache"))
LOCK_FILE = RUNTIME_DIR / "local-ia-tray.lock"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_RUN_VALUE = "KAIRO Sleep"
LEGACY_WINDOWS_RUN_VALUE = "LOCAL_IA Tray"


def autostart_enabled(settings=None) -> bool:
    if settings is None:
        from PySide6.QtCore import QSettings

        settings = QSettings("KAIRO", "LocalIA")
    return bool(settings.value("background/autostart", True, type=bool))


def set_autostart_enabled(enabled: bool, settings=None) -> None:
    if settings is None:
        from PySide6.QtCore import QSettings

        settings = QSettings("KAIRO", "LocalIA")
    settings.setValue("background/autostart", bool(enabled))
    settings.sync()
    if enabled:
        install_autostart()
    else:
        disable_autostart()


def service_running() -> bool:
    from PySide6.QtCore import QLockFile

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(LOCK_FILE))
    if not lock.tryLock(0):
        return True
    lock.unlock()
    return False


def habits_due_to_notify(data, now, notified=None):
    from local_ia.tools.habitude import habitudes_a_faire

    notified = notified if notified is not None else set()
    due = []
    day = now.date().isoformat()
    for habit in habitudes_a_faire(data, now):
        key = (str(habit.get("task", "")).casefold(), day)
        if key not in notified:
            notified.add(key)
            due.append(habit)
    return due


def _desktop_quote(value: str | Path) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def install_autostart() -> None:
    if IS_WINDOWS:
        import winreg

        command = subprocess.list2cmdline(
            (_tray_python_executable(), str(SLEEP_SCRIPT))
        )
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            winreg.SetValueEx(key, WINDOWS_RUN_VALUE, 0, winreg.REG_SZ, command)
            try:
                winreg.DeleteValue(key, LEGACY_WINDOWS_RUN_VALUE)
            except FileNotFoundError:
                pass
        return

    AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
    command = " ".join(
        (
            _desktop_quote(sys.executable),
            _desktop_quote(SLEEP_SCRIPT),
        )
    )
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=KAIRO Sleep\n"
        "Comment=Service de fond KAIRO\n"
        f"Exec={command}\n"
        "Terminal=false\n"
        "X-KDE-autostart-after=panel\n"
    )

    LEGACY_AUTOSTART_FILE.unlink(missing_ok=True)
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
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                WINDOWS_RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, LEGACY_WINDOWS_RUN_VALUE)
        except FileNotFoundError:
            pass
        return

    AUTOSTART_FILE.unlink(missing_ok=True)
    LEGACY_AUTOSTART_FILE.unlink(missing_ok=True)


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
    if service_running():
        return
    if autostart_enabled():
        install_autostart()
    subprocess.Popen(
        [_tray_python_executable(), str(SLEEP_SCRIPT)],
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


def launch_gui() -> subprocess.Popen:
    return subprocess.Popen(
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
    from PySide6.QtCore import QLockFile, QThread, QTimer, Signal
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    if autostart_enabled():
        install_autostart()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(LOCK_FILE))
    if not lock.tryLock(0):
        return 0

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    tray_available = QSystemTrayIcon.isSystemTrayAvailable()

    tray = QSystemTrayIcon(_create_icon()) if tray_available else QSystemTrayIcon()
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
        set_autostart_enabled(False)

    disable_action = menu.addAction("Désactiver le démarrage automatique")
    disable_action.triggered.connect(disable_tray)
    tray.setContextMenu(menu)

    def handle_activation(reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            open_application()

    tray.activated.connect(handle_activation)
    if tray_available:
        tray.show()

    from local_ia.core.memory import init_database
    from local_ia.core.notifications import publish as publish_notification
    from local_ia.tools.reminders import dispatch_due
    from local_ia.tools.habitude import charger, generer_resultat_habitude, marquer_habitude_notifiee

    class HabitMessageTask(QThread):
        completed = Signal(object)

        def __init__(self, habit, city):
            super().__init__(app)
            self.habit = habit
            self.city = city

        def run(self):
            try:
                message = generer_resultat_habitude({"ville": self.city}, self.habit)
            except Exception as error:
                message = f"C'est le moment de {self.habit.get('task', 'ton habitude')}. {error}"
            self.completed.emit({"task": self.habit.get("task", "Habitude"), "message": str(message)})

    reminder_connection = init_database()
    app.aboutToQuit.connect(reminder_connection.close)
    notified_habits = set()
    notified_day = [None]
    active_habit_tasks = set()

    def show_reminder(reminder: dict) -> None:
        message = str(reminder.get("title", "Rappel"))
        if reminder.get("repeat"):
            message += "\nRappel récurrent."
        tray.showMessage(
            "Rappel KAIRO",
            message,
            QSystemTrayIcon.MessageIcon.Information,
            10000,
        )

    def check_reminders() -> None:
        try:
            dispatch_due(reminder_connection, show_reminder)
        except Exception as error:
            tray.showMessage(
                "Rappels KAIRO indisponibles",
                str(error),
                QSystemTrayIcon.MessageIcon.Warning,
                10000,
            )

    def check_habits() -> None:
        now = datetime.now()
        if notified_day[0] != now.date():
            notified_habits.clear()
            notified_day[0] = now.date()
        try:
            data = charger()
            due_habits = habits_due_to_notify(data, now, notified_habits)
            for habit in due_habits:
                marquer_habitude_notifiee(data, habit, now)
                task = HabitMessageTask(dict(habit), data.get("ville", "Paris"))
                active_habit_tasks.add(task)

                def deliver(result, worker=task):
                    title = str(result.get("task", "Habitude"))
                    message = str(result.get("message", ""))
                    tray.showMessage(
                        f"Habitude KAIRO · {title}",
                        message,
                        QSystemTrayIcon.MessageIcon.Information,
                        10000,
                    )
                    publish_notification(reminder_connection, "habit", title, message)
                    active_habit_tasks.discard(worker)

                task.completed.connect(deliver)
                task.finished.connect(lambda worker=task: active_habit_tasks.discard(worker))
                task.start()
        except Exception as error:
            tray.showMessage(
                "Habitudes KAIRO indisponibles",
                str(error),
                QSystemTrayIcon.MessageIcon.Warning,
                10000,
            )

    reminder_timer = QTimer()
    reminder_timer.setInterval(30_000)
    reminder_timer.timeout.connect(check_reminders)
    reminder_timer.start()
    habit_timer = QTimer()
    habit_timer.setInterval(30_000)
    habit_timer.timeout.connect(check_habits)
    habit_timer.start()
    check_reminders()
    check_habits()
    return app.exec()