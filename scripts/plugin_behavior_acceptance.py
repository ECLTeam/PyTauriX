# ============================================================
# PyTauriX
# 文件作用：驱动插件行为验收，收集全局快捷键、通知与默认程序的真实证据。
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
EXAMPLE = ROOT / "examples" / "plugin_behavior" / "main.py"
RUN_TIMEOUT = 240.0

CHECKS: tuple[tuple[str, str, bool], ...] = (
    ("shortcut_registered", "快捷键注册后 is_registered 为真", True),
    ("shortcut_fired", "合成或人工按键触发了处理器", True),
    ("shortcut_duplicate_rejected", "同一快捷键重复注册被拒绝", True),
    ("shortcut_unregistered", "注销后 is_registered 为假", True),
    ("shortcut_unregister_all", "批量注销后 is_registered 为假", True),
    ("notification_permission_granted", "通知权限状态为 granted", True),
    ("notification_visible", "通知真实出现在屏幕上", False),
    ("opener_url_hit", "默认浏览器访问到本地服务", True),
    ("opener_path_opened", "默认程序打开了探测文件", False),
    ("opener_revealed", "文件管理器选中了探测文件", False),
)


def _pump(stream: object, sink: queue.Queue[str | None]) -> None:
    """
    逐行转发子进程输出，结束时放入哨兵。

    :param stream: 子进程标准输出
    :param sink: 行队列
    """
    assert hasattr(stream, "__iter__")
    for line in stream:  # type: ignore[union-attr]
        sink.put(line.rstrip())
    sink.put(None)


def _run(output: Path) -> tuple[dict[str, object] | None, int, list[str], list[str]]:
    """
    启动示例应用并等待其写出结果。

    :param output: 原始结果文件路径
    :return: 结果字典、退出码、日志行、异常说明
    """
    environment = dict(
        os.environ,
        PYTARUIX_PLUGIN_BEHAVIOR_OUT=str(output),
        PYTHONUTF8="1",
        PYTHONUNBUFFERED="1",
    )
    process = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    sink: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_pump, args=(process.stdout, sink), daemon=True).start()
    lines: list[str] = []
    problems: list[str] = []
    payload: dict[str, object] | None = None
    deadline = time.monotonic() + RUN_TIMEOUT
    while True:
        if time.monotonic() > deadline:
            problems.append(f"timed out after {RUN_TIMEOUT:.0f}s")
            process.kill()
            break
        try:
            line = sink.get(timeout=0.2)
        except queue.Empty:
            continue
        if line is None:
            break
        lines.append(line)
        if line.startswith("PLUGIN_BEHAVIOR_RESULT "):
            payload = json.loads(line.removeprefix("PLUGIN_BEHAVIOR_RESULT "))
    code = process.wait(timeout=30)
    return payload, code, lines, problems


def _judge(payload: dict[str, object]) -> dict[str, bool]:
    """
    把原始结果折算为判据字典。

    :param payload: 应用写出的结果
    :return: 判据名到布尔值
    """
    permission = str(payload.get("notification_permission_state", ""))
    return {
        "shortcut_registered": payload.get("shortcut_registered") is True,
        "shortcut_fired": payload.get("shortcut_fired") is True,
        "shortcut_duplicate_rejected": payload.get("shortcut_duplicate_rejected") is True,
        "shortcut_unregistered": payload.get("shortcut_unregistered") is True,
        "shortcut_unregister_all": payload.get("shortcut_unregister_all") is True,
        "notification_permission_granted": permission == "granted",
        "notification_visible": payload.get("notification_visible") is True,
        "opener_url_hit": payload.get("opener_url_hit") is True,
        "opener_path_opened": payload.get("opener_path_opened") is True,
        "opener_revealed": payload.get("opener_revealed") is True,
    }


def _render(judged: dict[str, bool], payload: dict[str, object], stamp: str) -> str:
    """
    生成便于复核的 Markdown 报告。

    :param judged: 判据结果
    :param payload: 原始结果
    :param stamp: 运行标识
    :return: Markdown 文本
    """
    rows = ["| 判据 | 说明 | 判定 | 结果 |", "| --- | --- | --- | --- |"]
    for name, description, automatic in CHECKS:
        mark = "通过" if judged.get(name) else "未通过"
        rows.append(f"| `{name}` | {description} | {'自动' if automatic else '人工确认'} | {mark} |")
    lines = [
        "# 插件行为验收报告",
        "",
        f"- 运行标识：{stamp}",
        f"- 平台：{sys.platform}",
        f"- 快捷键：{payload.get('accelerator', '')}",
        f"- 是否需要人工按键：{'是' if payload.get('shortcut_manual') else '否'}",
        f"- 通知权限：{payload.get('notification_permission_state', '')}",
        "",
        *rows,
        "",
        "原始结果见同目录 `raw.json`，应用输出见 `console.log`。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """
    执行一次插件行为验收并写出报告。

    :return: 全部判据通过返回 0
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = ROOT / "artifacts" / f"plugin-behavior-{stamp}"
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / "raw.json"
    print(f"使用示例 {EXAMPLE.relative_to(ROOT)}，按屏幕提示操作。", flush=True)
    payload, code, lines, problems = _run(raw)
    (directory / "console.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for line in lines:
        print(line, flush=True)
    if payload is None or not raw.is_file():
        payload = json.loads(raw.read_text(encoding="utf-8")) if raw.is_file() else {}
    judged = _judge(payload)
    (directory / "report.json").write_text(
        json.dumps(
            {
                "checks": judged,
                "exit_code": code,
                "payload": payload,
                "problems": problems,
                "started_at": stamp,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (directory / "report.md").write_text(_render(judged, payload, stamp), encoding="utf-8")
    failed = [name for name, _, _ in CHECKS if not judged[name]]
    print("", flush=True)
    for name, description, automatic in CHECKS:
        state = "通过" if judged[name] else "未通过"
        mode = "自动" if automatic else "人工"
        print(f"[{state}] {name}（{mode}）：{description}", flush=True)
    if problems:
        for problem in problems:
            print(f"[异常] {problem}", flush=True)
    print(f"\n报告目录 {directory}", flush=True)
    return 0 if not failed and not problems and code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
