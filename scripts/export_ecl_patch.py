# PytaruiX
# 文件作用：核对原 ECL 工作区摘要后导出隔离副本的最终迁移补丁。
# 公开接口：无；只读来源，输出必须位于本项目 artifacts。
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path


def main() -> None:
    """
    验证迁移涉及的来源未变，导出文本变更；生成资源不进入补丁，也不修改原 ECL。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    artifacts = (Path(__file__).resolve().parents[1] / "artifacts").resolve()
    output = args.output.resolve()
    if not output.is_relative_to(artifacts):
        parser.error("Patch must be written inside project artifacts")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    source = Path(baseline["source"]).resolve()
    snapshot = args.snapshot.resolve()
    changes: list[str] = []
    files: list[str] = []
    for name, expected_hash in sorted(baseline["files_sha256"].items()):
        original = (source / name).resolve()
        current = (snapshot / name).resolve()
        if not original.is_relative_to(source) or not current.is_relative_to(snapshot):
            raise ValueError(f"Snapshot path escapes root: {name}")
        following = current.read_bytes()
        if hashlib.sha256(following).hexdigest() == expected_hash:
            continue
        previous = original.read_bytes()
        if hashlib.sha256(previous).hexdigest() != expected_hash:
            raise RuntimeError(f"Original ECL changed since snapshot: {name}")
        if previous == following:
            continue
        before = previous.decode("utf-8").replace("\r\n", "\n")
        after = following.decode("utf-8").replace("\r\n", "\n")
        if before == after:
            continue
        files.append(name)
        # 保留来源中未变行的 CRLF/LF，避免补丁在混合换行文件上无法应用。
        original_lines = previous.decode("utf-8").splitlines(keepends=True)
        before_lines = before.splitlines(keepends=True)
        after_lines = after.splitlines(keepends=True)
        newline = "\r\n" if previous.count(b"\r\n") > previous.count(b"\n") / 2 else "\n"
        migrated_lines: list[str] = []
        for operation, start, end, new_start, new_end in difflib.SequenceMatcher(
            a=before_lines, b=after_lines, autojunk=False
        ).get_opcodes():
            if operation == "equal":
                migrated_lines.extend(original_lines[start:end])
            elif operation in {"insert", "replace"}:
                migrated_lines.extend(line.replace("\n", newline) for line in after_lines[new_start:new_end])
        changes.extend(
            difflib.unified_diff(
                original_lines,
                migrated_lines,
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )
    output.write_bytes("".join(changes).encode("utf-8"))
    print(json.dumps({"patch": str(output), "files": files}, ensure_ascii=False))


if __name__ == "__main__":
    main()
