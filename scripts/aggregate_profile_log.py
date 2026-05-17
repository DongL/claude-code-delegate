#!/usr/bin/env python3
"""Aggregate CLAUDE_DELEGATE_PROFILE_LOG JSONL records into a summary.

Default output is concise plain text optimized for orchestrator-side review.
Use --json for machine-readable output.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from typing import Any


def load_records(path: str) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping empty and malformed lines."""
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    if total == 0:
        return {"total_records": 0}

    error_count = sum(1 for r in records if r.get("isError"))
    success_count = total - error_count

    model_counts: Counter[str] = Counter()
    effort_counts: Counter[str] = Counter()
    task_type_counts: Counter[str] = Counter()
    mcp_mode_counts: Counter[str] = Counter()
    terminal_reason_counts: Counter[str] = Counter()

    input_tokens_total = 0
    cache_read_total = 0
    output_tokens_total = 0
    input_tokens_n = 0
    cache_read_n = 0
    output_tokens_n = 0

    cost_total = 0.0
    cost_n = 0

    original_chars_total = 0
    prepared_chars_total = 0
    original_chars_n = 0
    prepared_chars_n = 0
    reduction_pcts: list[int] = []

    for r in records:
        model_counts[r.get("model") or "unknown"] += 1
        effort_counts[r.get("effort") or "unknown"] += 1
        task_type_counts[r.get("taskType") or "unknown"] += 1
        mcp_mode_counts[r.get("mcpMode") or "unknown"] += 1
        terminal_reason_counts[r.get("terminalReason") or "unknown"] += 1

        usage = r.get("usage")
        if isinstance(usage, dict):
            v = usage.get("input_tokens")
            if isinstance(v, int):
                input_tokens_total += v
                input_tokens_n += 1

            v = usage.get("cache_read_input_tokens")
            if isinstance(v, int):
                cache_read_total += v
                cache_read_n += 1

            v = usage.get("output_tokens")
            if isinstance(v, int):
                output_tokens_total += v
                output_tokens_n += 1

        cost = r.get("totalCostUsd")
        if isinstance(cost, (int, float)):
            cost_total += float(cost)
            cost_n += 1

        orig = r.get("originalPromptChars")
        if isinstance(orig, int):
            original_chars_total += orig
            original_chars_n += 1

        prep = r.get("preparedPromptChars")
        if isinstance(prep, int):
            prepared_chars_total += prep
            prepared_chars_n += 1

        pct = r.get("promptReductionPct")
        if isinstance(pct, int):
            reduction_pcts.append(pct)

    # Aggregate cache hit ratio: sum(cache_read) / sum(input + cache_read)
    aggregate_denom = input_tokens_total + cache_read_total
    aggregate_cache_hit = (
        cache_read_total / aggregate_denom if aggregate_denom > 0 else None
    )

    result: dict[str, Any] = {
        "total_records": total,
        "success_count": success_count,
        "error_count": error_count,
        "model_distribution": dict(model_counts.most_common()),
        "effort_distribution": dict(effort_counts.most_common()),
        "task_type_distribution": dict(task_type_counts.most_common()),
        "mcp_mode_distribution": dict(mcp_mode_counts.most_common()),
        "terminal_reason_distribution": dict(terminal_reason_counts.most_common()),
        "tokens": {
            "input_tokens": {
                "total": input_tokens_total,
                "avg": _div(input_tokens_total, input_tokens_n),
                "records_with_field": input_tokens_n,
            },
            "cache_read_input_tokens": {
                "total": cache_read_total,
                "avg": _div(cache_read_total, cache_read_n),
                "records_with_field": cache_read_n,
            },
            "output_tokens": {
                "total": output_tokens_total,
                "avg": _div(output_tokens_total, output_tokens_n),
                "records_with_field": output_tokens_n,
            },
            "aggregate_cache_hit_ratio": aggregate_cache_hit,
        },
        "cost": {
            "total_usd": round(cost_total, 6),
            "avg_usd": _div_round(cost_total, cost_n, 6),
            "records_with_cost": cost_n,
        },
        "prompt_chars": {
            "original": {
                "total": original_chars_total,
                "avg": _div(original_chars_total, original_chars_n),
                "records_with_field": original_chars_n,
            },
            "prepared": {
                "total": prepared_chars_total,
                "avg": _div(prepared_chars_total, prepared_chars_n),
                "records_with_field": prepared_chars_n,
            },
            "reduction_pct_avg": _div(sum(reduction_pcts), len(reduction_pcts)),
            "reduction_pct_records": len(reduction_pcts),
        },
    }
    return result


def _div(total: int, n: int) -> float | None:
    return total / n if n > 0 else None


def _div_round(total: float, n: int, digits: int = 6) -> float | None:
    return round(total / n, digits) if n > 0 else None


def _should_show(dist: dict[str, int]) -> bool:
    """Show distribution if it has >=2 entries or a single non-'unknown' entry."""
    if len(dist) >= 2:
        return True
    if len(dist) == 1 and next(iter(dist)) != "unknown":
        return True
    return False


def _fmt_num(val: float | int | None) -> str:
    if val is None:
        return "-"
    if isinstance(val, float):
        return f"{val:.1f}"
    return str(val)


def format_text(result: dict[str, Any]) -> str:
    if result["total_records"] == 0:
        return "No records in profile log."

    lines: list[str] = []
    lines.append(f"Records: {result['total_records']}")
    lines.append(
        f"  Success: {result['success_count']}  Error: {result['error_count']}"
    )

    def _add_dist(label: str, dist: dict[str, int]) -> None:
        if not _should_show(dist):
            return
        lines.append(f"  {label}:")
        for k, v in dist.items():
            lines.append(f"    {k}: {v}")

    _add_dist("Model", result["model_distribution"])
    _add_dist("Effort", result["effort_distribution"])
    _add_dist("TaskType", result["task_type_distribution"])
    _add_dist("MCP Mode", result["mcp_mode_distribution"])
    _add_dist("TerminalReason", result["terminal_reason_distribution"])

    tok = result["tokens"]
    lines.append("")
    lines.append("Tokens:")
    lines.append(
        f"  Input:       total={tok['input_tokens']['total']}, "
        f"avg={_fmt_num(tok['input_tokens']['avg'])}"
    )
    lines.append(
        f"  Cache Read:  total={tok['cache_read_input_tokens']['total']}, "
        f"avg={_fmt_num(tok['cache_read_input_tokens']['avg'])}"
    )
    lines.append(
        f"  Output:      total={tok['output_tokens']['total']}, "
        f"avg={_fmt_num(tok['output_tokens']['avg'])}"
    )

    if tok["aggregate_cache_hit_ratio"] is not None:
        lines.append(
            f"  Cache hit ratio: {tok['aggregate_cache_hit_ratio']:.2%}"
        )

    cost = result["cost"]
    if cost["total_usd"] > 0:
        lines.append("")
        lines.append("Cost:")
        lines.append(f"  Total: ${cost['total_usd']:.4f}")
        if cost["avg_usd"] is not None:
            lines.append(f"  Avg:   ${cost['avg_usd']:.4f}")

    pc = result["prompt_chars"]
    lines.append("")
    lines.append("Prompt chars:")
    lines.append(
        f"  Original:  total={pc['original']['total']}, "
        f"avg={_fmt_num(pc['original']['avg'])}"
    )
    lines.append(
        f"  Prepared:  total={pc['prepared']['total']}, "
        f"avg={_fmt_num(pc['prepared']['avg'])}"
    )
    if pc["reduction_pct_avg"] is not None:
        lines.append(f"  Reduction: avg={pc['reduction_pct_avg']:.1f}%")

    return "\n".join(lines)


def format_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Aggregate CLAUDE_DELEGATE_PROFILE_LOG JSONL records."
    )
    parser.add_argument(
        "profile_log",
        nargs="?",
        help="Path to profile JSONL. Defaults to CLAUDE_DELEGATE_PROFILE_LOG env var.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of plain text.",
    )
    args = parser.parse_args()

    path = args.profile_log or os.environ.get("CLAUDE_DELEGATE_PROFILE_LOG")
    if not path:
        print(
            "No profile log specified. Provide path or set CLAUDE_DELEGATE_PROFILE_LOG.",
            file=sys.stderr,
        )
        return 1

    if not os.path.isfile(path):
        print(f"Profile log not found: {path}", file=sys.stderr)
        return 1

    records = load_records(path)
    result = aggregate(records)

    if args.json:
        print(format_json(result))
    else:
        print(format_text(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
