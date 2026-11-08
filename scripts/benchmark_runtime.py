# ============================================================
# PyTauriX
# 文件作用：在独立进程中采集解释器启动、导入、运行时信息与 Context 准备耗时。
# 公开接口：main。
# ============================================================
from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

SCENARIOS = ("interpreter", "import", "runtime_info", "context")


def _command(name: str, python: str, resource: Path) -> list[str]:
    if name == "interpreter":
        return [python, "-I", "-c", "pass"]
    if name == "import":
        return [python, "-I", "-c", "import pytaurix"]
    if name == "runtime_info":
        return [python, "-I", "-c", "from pytaurix import get_runtime_info; get_runtime_info()"]
    return [
        python,
        "-I",
        "-c",
        "import sys; from pathlib import Path; from pytaurix import context_factory; "
        "context_factory(Path(sys.argv[1]))",
        str(resource),
    ]


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _sample(name: str, python: str, resource: Path, timeout: float) -> float:
    start = time.perf_counter()
    process = subprocess.run(
        _command(name, python, resource), capture_output=True, text=True, timeout=timeout, check=False
    )
    elapsed = time.perf_counter() - start
    if process.returncode != 0:
        raise RuntimeError(f"{name} failed: {process.stdout}{process.stderr}")
    return elapsed


def main() -> None:
    """
    采集单调时钟样本并输出原始值与 P50/P95。

    :param sys.argv: --out 必填；--python/--resource/--samples 可选
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--resource", default=str(Path(__file__).resolve().parents[1] / "examples" / "minimal"))
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=120.0)
    arguments = parser.parse_args()
    if arguments.samples < 2:
        raise SystemExit("--samples must be at least 2")

    resource = Path(arguments.resource).resolve()
    report: dict[str, object] = {
        "label": arguments.label,
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "interpreter": arguments.python,
            "resource": str(resource),
            "platform": platform.platform(),
        },
        "warmup_runs": 1,
        "samples_per_scenario": arguments.samples,
        "results": {},
    }
    results: dict[str, object] = {}
    for name in SCENARIOS:
        _sample(name, arguments.python, resource, arguments.timeout)
        samples = [_sample(name, arguments.python, resource, arguments.timeout) for _ in range(arguments.samples)]
        results[name] = {
            "samples_s": [round(value, 6) for value in samples],
            "min_s": round(min(samples), 6),
            "p50_s": round(_percentile(samples, 0.50), 6),
            "p95_s": round(_percentile(samples, 0.95), 6),
            "max_s": round(max(samples), 6),
        }
    report["results"] = results

    output = Path(arguments.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"BENCHMARKED {arguments.label} -> {output}")


if __name__ == "__main__":
    main()
