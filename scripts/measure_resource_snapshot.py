# ============================================================
# PyTauriX
# 文件作用：测量 Context 资源快照随前端目录规模的时间与内存曲线，
#          为资源加载策略选择提供同源数据。
# 公开接口：main。
#
# 方法说明：
#   - 每个样本在独立子进程执行：先生成固定规模的合成前端目录，再在进程内
#     以单调时钟测量 context_factory 的墙钟时间，并用 GetProcessMemoryInfo
#     采集调用前后的工作集与提交内存增量。
#   - 快照时间受操作系统文件缓存影响，脚本不主动清缓存；结论注明冷热差异
#     需要单独实验，本脚本只报告重复启动（热缓存）曲线。
#   - 子进程使用已安装的 pytaurix wheel（--python 指定解释器），源码目录
#     的 editable 安装与本脚本无关。
# ============================================================
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 规模点：xs 为 examples/minimal 实物；s 复刻 ECL 真实前端（92 个文件、约 6 MiB）；
# m/l/xl 为外推压力点，文件内容以可重复的伪随机字节填充。
SCALES: dict[str, tuple[int, int]] = {
    "xs": (4, 8 * 1024),
    "s": (92, 6 * 1024 * 1024),
    "m": (500, 30 * 1024 * 1024),
    "l": (2000, 120 * 1024 * 1024),
    "xl": (5000, 300 * 1024 * 1024),
}


class _ProcessMemoryCounters(ctypes.Structure):
    """GetProcessMemoryInfo 所需的 PROCESS_MEMORY_COUNTERS 结构。"""

    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("PageFaultCount", ctypes.wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _memory_usage() -> dict[str, int]:
    """返回当前进程的工作集与提交内存（字节）；仅支持 Windows。"""
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
    psapi = ctypes.windll.psapi
    kernel32 = ctypes.windll.kernel32
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.wintypes.DWORD,
    ]
    kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    handle = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        raise OSError(f"GetProcessMemoryInfo failed: {ctypes.windll.kernel32.GetLastError()}")
    return {
        "working_set": counters.WorkingSetSize,
        "commit": counters.PagefileUsage,
        "peak_working_set": counters.PeakWorkingSetSize,
        "peak_commit": counters.PeakPagefileUsage,
    }


def _generate_frontend(root: Path, files: int, total_bytes: int) -> None:
    """生成合成前端目录：目录树深度固定，文件大小按份额分布近似真实产物。"""
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise SystemExit(f"目标目录非空：{root}")
    (root / "tauri.conf.json").write_text(
        json.dumps(
            {
                "$schema": "https://schema.tauri.app/config/2",
                "productName": "snapshot-bench",
                "version": "0.1.0",
                "identifier": "top.eclteam.pytaurix.snapshot-bench",
                "build": {"frontendDist": "."},
                "app": {"windows": [{"label": "main", "title": "snapshot-bench"}], "withGlobalTauri": True},
                "bundle": {"active": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "index.html").write_text("<!doctype html><title>snapshot-bench</title>", encoding="utf-8")
    remaining_files, remaining_bytes = files - 1, total_bytes - 40
    for index in range(remaining_files):
        # 前四分之三放入 assets/ 小文件，其余生成少量大文件。
        share = remaining_bytes // max(1, remaining_files * (3 if index < remaining_files * 0.75 else 1) // 3)
        share = max(share, 64)
        payload = bytes((index * 31 + offset) % 251 for offset in range(share))
        if index < remaining_files * 0.75:
            target = root / "assets" / f"chunk-{index:05d}.js"
        else:
            target = root / "assets" / f"bundle-{index:05d}.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        remaining_bytes -= share


def _sample_body(resource: Path) -> dict[str, float | int]:
    """进程内测量：导入、context_factory 耗时与内存增量；Context 需持有到采样结束。"""
    import_time_start = time.perf_counter()
    from pytaurix import context_factory

    import_elapsed = time.perf_counter() - import_time_start
    before = _memory_usage()
    start = time.perf_counter()
    context = context_factory(resource)
    elapsed = time.perf_counter() - start
    after = _memory_usage()
    del context
    return {
        "import_s": import_elapsed,
        "context_s": elapsed,
        "working_set_delta": after["working_set"] - before["working_set"],
        "commit_delta": after["commit"] - before["commit"],
        "peak_working_set_delta": after["peak_working_set"] - before["peak_working_set"],
        "peak_commit_delta": after["peak_commit"] - before["peak_commit"],
    }


def _run_sample(python: str, resource: Path, timeout: float) -> dict[str, float | int]:
    script = (
        "import json,sys;sys.path.insert(0,sys.argv[1]);"
        "from measure_resource_snapshot import _sample_body;"
        "print(json.dumps(_sample_body(__import__('pathlib').Path(sys.argv[2]))))"
    )
    process = subprocess.run(
        [python, "-I", "-c", script, str(REPO_ROOT / "scripts"), str(resource)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"sample failed: {process.stdout}{process.stderr}")
    return json.loads(process.stdout.strip().splitlines()[-1])


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def main() -> None:
    """生成合成前端并采样输出 JSON 报告。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="snapshot-baseline")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--workspace", default=str(REPO_ROOT / "artifacts" / "resource-snapshot"))
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--scales", default=",".join(SCALES))
    parser.add_argument("--timeout", type=float, default=300.0)
    arguments = parser.parse_args()
    if arguments.samples < 2:
        raise SystemExit("--samples must be at least 2")

    workspace = Path(arguments.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "label": arguments.label,
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "interpreter": arguments.python,
            "platform": platform.platform(),
        },
        "note": "重复启动（热 OS 文件缓存）曲线；冷缓存未测量",
    }
    scales: dict[str, dict[str, object]] = {}

    for scale in arguments.scales.split(","):
        if scale not in SCALES:
            raise SystemExit(f"未知规模：{scale}")
        files, total_bytes = SCALES[scale]
        frontend = workspace / f"frontend-{scale}"
        if not frontend.exists():
            _generate_frontend(frontend, files, total_bytes)
        samples = [_run_sample(arguments.python, frontend, arguments.timeout) for _ in range(arguments.samples)]
        context_times = [sample["context_s"] for sample in samples]
        scales[scale] = {
            "files": files,
            "total_bytes": total_bytes,
            "context_s_p50": _percentile(context_times, 0.5),
            "context_s_p95": _percentile(context_times, 0.95),
            "context_s_stdev": statistics.stdev(context_times),
            "working_set_delta_median": statistics.median([s["working_set_delta"] for s in samples]),
            "commit_delta_median": statistics.median([s["commit_delta"] for s in samples]),
            "peak_commit_delta_median": statistics.median([s["peak_commit_delta"] for s in samples]),
            "peak_working_set_delta_median": statistics.median([s["peak_working_set_delta"] for s in samples]),
            "import_s_p50": _percentile([s["import_s"] for s in samples], 0.5),
            "raw": samples,
        }

    report["scales"] = scales
    output = Path(arguments.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {scale: {key: value for key, value in data.items() if key != "raw"} for scale, data in scales.items()},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
