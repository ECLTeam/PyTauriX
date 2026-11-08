# ============================================================
# PyTauriX
# 文件作用：两轮真实桌面验收，覆盖取消、协议、fs、单实例与窗口状态。
# 公开接口：无。
# ============================================================
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "acceptance" / "main.py"
ROUND_TIMEOUT = 120.0
SECOND_TIMEOUT = 40.0


def _environment(round_name: str) -> dict[str, str]:
    """
    构造子进程环境，保持输出可解析。

    :param round_name: 轮次标识
    :return: 环境变量副本
    """
    environment = dict(
        os.environ,
        PYTARUIX_ACCEPTANCE="1",
        PYTARUIX_ACCEPTANCE_ROUND=round_name,
        PYTHONUTF8="1",
        PYTHONUNBUFFERED="1",
    )
    return environment


def _pump(stream: object, sink: queue.Queue[str | None]) -> None:
    """
    把子进程输出逐行放入队列，结束时放入 None 作为哨兵。

    :param stream: 子进程标准输出
    :param sink: 行队列
    """
    assert hasattr(stream, "__iter__")
    for line in stream:  # type: ignore[union-attr]
        sink.put(line.rstrip())
    sink.put(None)


def _collect(
    round_name: str, spawn_second: bool, timeout: float
) -> tuple[dict[str, object] | None, int, list[str], list[str], list[str]]:
    """
    跑一轮验收，按需在检查完成时拉起第二实例。

    :param round_name: 轮次标识
    :param spawn_second: 是否在 CHECKS_DONE 后启动第二实例
    :param timeout: 本轮超时秒数
    :return: 结果、退出码、日志、第二实例日志、异常说明
    """
    lines: list[str] = []
    second_lines: list[str] = []
    problems: list[str] = []
    result: dict[str, object] | None = None
    process = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        env=_environment(round_name),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    sink: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_pump, args=(process.stdout, sink), daemon=True).start()
    second: subprocess.Popen[str] | None = None
    deadline = time.monotonic() + timeout
    finished = False
    while not finished:
        if time.monotonic() > deadline:
            problems.append(f"round {round_name}: timed out after {timeout:.0f}s")
            process.kill()
            break
        try:
            line = sink.get(timeout=0.2)
        except queue.Empty:
            continue
        if line is None:
            finished = True
            break
        lines.append(line)
        if line.startswith("ACCEPTANCE_RESULT "):
            result = json.loads(line.removeprefix("ACCEPTANCE_RESULT "))
        if spawn_second and second is None and "CHECKS_DONE" in line:
            second = subprocess.Popen(
                [sys.executable, str(EXAMPLE)],
                env=_environment("second"),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
    code = process.wait(timeout=30)
    if second is not None:
        try:
            second_output, _ = second.communicate(timeout=SECOND_TIMEOUT)
            second_lines = [item for item in (second_output or "").splitlines() if item.strip()]
        except subprocess.TimeoutExpired:
            problems.append("second instance did not exit in time")
            second.kill()
            second_output, _ = second.communicate()
            second_lines = [item for item in (second_output or "").splitlines() if item.strip()]
    return result, code, lines, second_lines, problems


def _verdict(first: dict[str, object], second: dict[str, object]) -> tuple[dict[str, bool], list[str]]:
    """
    汇总两轮数据，产出布尔判据与失败说明。

    :param first: 第一轮结果
    :param second: 第二轮结果
    :return: 判据表与失败原因
    """
    checks: dict[str, bool] = {}
    notes: list[str] = []
    frontend = first.get("frontend") or {}
    assert isinstance(frontend, dict)
    for name in ("cancel_abort", "cancel_ack", "protocol_status", "protocol_body", "fs_roundtrip"):
        value = frontend.get(name)
        checks[name] = value is True
        if value is not True:
            notes.append(f"{name} failed in the webview")
    checks["python_saw_cancel"] = first.get("python_saw_cancel") is True
    if not checks["python_saw_cancel"]:
        notes.append("python never observed request.cancelled")
    checks["second_instance"] = first.get("second_instance") is True
    if not checks["second_instance"]:
        notes.append(str(first.get("second_instance_reason") or "second instance callback missing"))
    first_size = first.get("geometry") or {}
    second_size = second.get("geometry") or {}
    assert isinstance(first_size, dict) and isinstance(second_size, dict)
    same = (
        abs(int(first_size.get("width", 0)) - int(second_size.get("width", -1))) <= 2
        and abs(int(first_size.get("height", 0)) - int(second_size.get("height", -1))) <= 2
    )
    checks["window_state_restored"] = same
    if not same:
        notes.append(f"geometry changed: {first_size} -> {second_size}")
    return checks, notes


def _write_report(directory: Path, payload: dict[str, object], transcript: list[str]) -> Path:
    """
    落盘 JSON 报告与原始输出。

    :param directory: 批次目录
    :param payload: 汇总数据
    :param transcript: 原始输出行
    :return: 报告路径
    """
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "report.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / "transcript.log").write_text("\n".join(transcript) + "\n", encoding="utf-8")
    checks = payload.get("checks") or {}
    assert isinstance(checks, dict)
    rows = "\n".join(f"| {name} | {'pass' if ok else 'fail'} |" for name, ok in checks.items())
    summary = (
        f"# 桌面验收 {payload['started_at']}\n\n"
        f"结论：{'全部通过' if payload['passed'] else '存在失败项'}\n\n"
        f"| 判据 | 结果 |\n| --- | --- |\n{rows}\n\n"
        f"平台：{payload['platform']}\n\n"
        f"原始输出：`transcript.log`，结构化结果：`report.json`。\n"
    )
    (directory / "summary.md").write_text(summary, encoding="utf-8")
    return report


def main() -> int:
    """
    执行两轮验收并写出报告。

    :return: 全通过返回 0
    """
    from pytaurix import _native

    required = {
        "plugin_fs_available": "plugin-fs",
        "plugin_window_state_available": "plugin-window-state",
        "plugin_single_instance_available": "plugin-single-instance",
    }
    missing = [feature for attr, feature in required.items() if not getattr(_native, attr, False)]
    if missing:
        print(
            "当前构建缺少插件：" + ", ".join(missing) + "\n"
            "请用全插件组合重建：\n"
            "  CARGO_BUILD_JOBS=1 maturin develop --locked --features "
            "plugin-fs,plugin-global-shortcut,plugin-notification,plugin-opener,"
            "plugin-single-instance,plugin-window-state",
            file=sys.stderr,
        )
        return 2
    started = datetime.now().astimezone()
    transcript: list[str] = []
    first, first_code, first_lines, second_lines, problems = _collect("1", True, ROUND_TIMEOUT)
    transcript += [f"[round1:{first_code}] {line}" for line in first_lines]
    transcript += [f"[second] {line}" for line in second_lines]
    if first is None:
        problems.append("round 1 produced no result line")
        first = {}
    second, second_code, second_out, _, more = _collect("2", False, ROUND_TIMEOUT)
    transcript += [f"[round2:{second_code}] {line}" for line in second_out]
    problems += more
    if second is None:
        problems.append("round 2 produced no result line")
        second = {}
    checks, notes = _verdict(first, second)
    payload = {
        "started_at": started.isoformat(timespec="seconds"),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "checks": checks,
        "notes": notes + problems,
        "round1": first,
        "round2": second,
        "passed": all(checks.values()) and not problems,
    }
    directory = ROOT / "artifacts" / f"desktop-acceptance-{started.strftime('%Y%m%d-%H%M%S')}"
    report = _write_report(directory, payload, transcript)
    print(json.dumps(checks, ensure_ascii=False, sort_keys=True))
    for note in payload["notes"]:
        print("注意：" + str(note), file=sys.stderr)
    print(f"报告：{report}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
