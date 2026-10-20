import os
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "local_ia_backup"
LOG_PATH = ROOT / "performance_baseline.log"


def ensure_backup() -> None:
    if BACKUP_DIR.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    guard = BACKUP_DIR / ".phase0_guard"
    if guard.exists():
        return
    for name in os.listdir(ROOT):
        if name == "local_ia_backup":
            continue
        src = ROOT / name
        dst = BACKUP_DIR / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    guard.write_text("phase0-created", encoding="utf-8")


def write_baseline_log(duration_ms: int, test_count: int) -> None:
    LOG_PATH.write_text(
        "request_id=baseline-2026-09-25\n"
        "route=full-suite\n"
        "model=local\n"
        "prompt_chars=2056\n"
        "history_messages=not_limited_baseline\n"
        "memory_items=unknown_baseline\n"
        "tools_count=10\n"
        "ollama_calls=not_measured_in_unit_suite\n"
        f"duration_ms={duration_ms}\n"
        "first_token_ms=not_measured\n"
        "tool_steps=not_measured\n"
        f"test_count={test_count}\n"
        "status=baseline_snapshot\n",
        encoding="utf-8",
    )


def main() -> None:
    ensure_backup()
    start = time.perf_counter()
    res = subprocess.run(
        ["python", "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    output = (res.stdout or "") + "\n" + (res.stderr or "")
    match = re.search(r"Ran\s+(\d+)\s+tests", output)
    count = int(match.group(1)) if match else 0
    write_baseline_log(duration_ms, count)
    print(f"backup={BACKUP_DIR}")
    print(f"tests={count}")
    print(f"duration_ms={duration_ms}")
    print(f"log={LOG_PATH}")


if __name__ == "__main__":
    main()
