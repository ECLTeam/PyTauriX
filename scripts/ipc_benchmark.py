# ============================================================
# PyTauriX
# 文件作用：以指定解释器运行真实 WebView IPC 基准并保存原始结果。
# 公开接口：main。
# ============================================================
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    """
    启动性能示例，解析前端回报的 IPC 结果并写入 JSON。

    :param sys.argv: --out 必填；--python/--label/--timeout 可选
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=180.0)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    example = root / "examples" / "performance" / "main.py"
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    result = subprocess.run(
        [arguments.python, str(example)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=arguments.timeout,
        check=False,
    )
    line = next((item for item in result.stdout.splitlines() if item.startswith("IPC_BENCH_RESULT ")), None)
    if result.returncode != 0 or line is None:
        raise SystemExit(f"IPC benchmark failed ({result.returncode}): {result.stdout}{result.stderr}")
    report = {
        "label": arguments.label,
        "generated_at": datetime.now(UTC).isoformat(),
        "python": arguments.python,
        "python_version": sys.version,
        "results": json.loads(line.removeprefix("IPC_BENCH_RESULT ")),
    }
    output = Path(arguments.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"BENCHMARKED {arguments.label} -> {output}")


if __name__ == "__main__":
    main()
