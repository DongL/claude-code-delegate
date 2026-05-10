#!/usr/bin/env python3
"""Profile record logger for Claude Code delegation."""

from __future__ import annotations

import json
from pathlib import Path


def append_profile_record(record: dict, profile_log_path: str) -> None:
    if not profile_log_path:
        return
    path = Path(profile_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
