from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class PerformanceTargetChecker:
    """Compare un benchmark aux objectifs de performance de la phase 18."""

    DEFAULT_TARGETS = {
        "simple_question": {"ollama_calls_max": 1, "total_ms_max": 1500, "tool_steps_max": 0},
        "simple_action": {"ollama_calls_max": 0, "total_ms_max": 300, "tool_steps_max": 0},
        "tool_request": {"ollama_calls_max": 3, "total_ms_max": 2000, "tool_steps_max": 3},
        "complex_task": {"ollama_calls_max": 4, "total_ms_max": 5000, "tool_steps_max": 4},
    }

    def evaluate(self, report: dict[str, Any]) -> dict[str, Any]:
        scenario_map = report.get("scenarios", {}) if isinstance(report, dict) else {}
        results: dict[str, Any] = {}
        summary = {"pass": 0, "fail": 0, "total": 0}

        for key, target in self.DEFAULT_TARGETS.items():
            scenario = scenario_map.get(key, {})
            ollama_calls = int(scenario.get("ollama_calls", 0))
            total_ms = int(scenario.get("total_ms", 0))
            tool_steps = int(scenario.get("tool_steps", scenario.get("tool_result_chars", 0) and 1 or 0))

            checks = {
                "ollama_calls": ollama_calls <= target["ollama_calls_max"],
                "total_ms": total_ms <= target["total_ms_max"],
                "tool_steps": tool_steps <= target["tool_steps_max"],
            }
            status = "pass" if all(checks.values()) else "fail"
            summary["total"] += 1
            summary["pass" if status == "pass" else "fail"] += 1
            results[key] = {
                "status": status,
                "observed": {
                    "ollama_calls": ollama_calls,
                    "total_ms": total_ms,
                    "tool_steps": tool_steps,
                },
                "targets": target,
                "checks": checks,
            }

        results["summary"] = summary
        return results


def main() -> None:
    path = ROOT / "performance_baseline.json"
    if path.exists():
        report = json.loads(path.read_text(encoding="utf-8"))
    else:
        report = {"scenarios": {}}
    evaluation = PerformanceTargetChecker().evaluate(report)
    print(json.dumps(evaluation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
