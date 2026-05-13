#!/usr/bin/env python3
"""Health check for claude-code-delegate.

Prints PASS/FAIL for each check, then HEALTHY or UNHEALTHY summary.
Exit 0 = all pass, Exit 1 = any failure.
Also importable: run_health_checks() -> (all_pass, results).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REQUIRED_SCRIPTS = [
    "pipeline.py",
    "invoker.py",
    "compact-claude-stream.py",
    "classifier.py",
    "envelope_builder.py",
    "run-pipeline.py",
]

_RUNTIME_CANDIDATES = [
    Path(".claude-delegate/runtime"),
    Path.home() / ".claude-delegate/runtime",
]


def run_health_checks() -> tuple[bool, list[dict]]:
    results: list[dict] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        results.append({"name": name, "passed": passed, "detail": detail})

    # python3 available
    py = shutil.which("python3")
    add("python3", bool(py), py or "not found")

    # claude on PATH
    claude_path = shutil.which("claude")
    require_claude = os.environ.get("CLAUDE_DELEGATE_HEALTH_REQUIRE_CLAUDE", "0") == "1"
    if require_claude and not claude_path:
        add("claude", False, "not on PATH (CLAUDE_DELEGATE_HEALTH_REQUIRE_CLAUDE=1)")
    elif not claude_path:
        add("claude", True, "not on PATH (optional)")
    else:
        add("claude", True, claude_path)

    # core scripts present
    for script in _REQUIRED_SCRIPTS:
        path = _SCRIPTS_DIR / script
        add(f"script/{script}", path.exists(), str(path))

    # runtime dir writable
    writable = None
    for candidate in _RUNTIME_CANDIDATES:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            test_file = candidate / ".health_check_write_test"
            test_file.write_text("")
            test_file.unlink()
            writable = str(candidate)
            break
        except OSError:
            continue
    add("runtime-writable", writable is not None, writable or "no writable runtime dir")

    # mcp package importable (optional, warn if missing)
    mcp_spec = importlib.util.find_spec("mcp")
    if mcp_spec is not None:
        add("mcp-package", True, f"{mcp_spec.origin}")
    else:
        add("mcp-package", True, "not installed (optional)")

    all_pass = all(r["passed"] for r in results)
    return all_pass, results


def _main() -> None:
    all_pass, results = run_health_checks()
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        line = f"{status} {r['name']}"
        if r["detail"]:
            line += f" ({r['detail']})"
        print(line)

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    failed_count = total - passed_count

    if all_pass:
        print(f"HEALTHY ({passed_count}/{total} passed)")
        sys.exit(0)
    else:
        print(f"UNHEALTHY ({passed_count}/{total} passed, {failed_count} failed)")
        sys.exit(1)


if __name__ == "__main__":
    _main()
