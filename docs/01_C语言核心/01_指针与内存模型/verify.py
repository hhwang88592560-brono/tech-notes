"""验证本课完整 C 程序、文档一致性与必要的编译诊断。只使用 Python 标准库。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
PRIMARY = ROOT.parent / "任务_01_指针与内存模型.out.md"
SECTIONS = ["00_导读", "10_要点", "20_动手", "30_自测", "99_复盘模板"]
CODE_PATTERN = re.compile(
    r"<!-- lesson-code: ([^|]+) \| (run|compile-only) -->\n```c\n(.*?)\n```",
    re.DOTALL,
)
REPORT: dict = {"status": "started", "commands": [], "checks": []}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    REPORT["checks"].append(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(args: list[str], timeout: int = 45) -> dict:
    record = {"argv": args, "cwd": str(ROOT), "status": "started"}
    REPORT["commands"].append(record)
    try:
        result = subprocess.run(
            args, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        record.update(status="timed_out", returncode=None)
        record["stdout"] = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        record["stderr"] = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        raise
    except OSError as exc:
        record.update(status="failed_to_start", returncode=None, error=str(exc))
        raise
    record.update(status="completed", returncode=result.returncode,
                  stdout=result.stdout, stderr=result.stderr)
    return record


def generated_files(text: str) -> tuple[dict[Path, str], list[tuple[str, str, str]]]:
    headings = list(re.finditer(r"(?m)^## (.+)$", text))
    require([m.group(1) for m in headings] == SECTIONS, "学习包恰好包含要求的五个二级标题")
    files = {}
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[match.end():end].strip()
        section = section.replace(f"]({ROOT.name}/", "](")
        name = match.group(1)
        filename = "99_复盘.md" if name == "99_复盘模板" else name + ".md"
        files[ROOT / filename] = f"# {name}\n\n{section}\n"
    codes = [(name.strip(), mode, code + "\n") for name, mode, code in CODE_PATTERN.findall(text)]
    require(len(codes) == 10, "找到四个实验、四个找错程序和两个设计题实现")
    require(len(re.findall(r"(?m)^#### \d+\.", text)) == 10, "自测题数为十题")
    require(text.count("> 参考答案：") == 10, "每题均有独立的参考答案引用块")
    require(len(re.findall(r"(?m)^```c$", text)) == len(codes), "所有 C 代码块都纳入验证")
    require(len({name for name, _, _ in codes}) == len(codes), "所有 C 源文件名唯一")
    for name, _, code in codes:
        target = (ROOT / name).resolve()
        require(target.is_relative_to(ROOT), f"生成路径在本课目录内：{name}")
        files[target] = code
    return files, codes


def compare_or_materialize(files: dict[Path, str], materialize: bool) -> None:
    for path, text in files.items():
        if not path.exists() and materialize:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        require(path.exists(), f"文件存在：{path.name}")
        require(path.read_text(encoding="utf-8") == text, f"文件与完整学习包一致：{path.name}")


def check_output(name: str, output: str, metrics: dict) -> None:
    lines = output.strip().splitlines()
    expected = {
        "examples/03_const.c": ["snapshot=10", "x=20 read_only=30 fixed_read=20", "x_after_alias=25 fixed_read=25"],
        "examples/04_volatile.c": ["regular=14", "observed=14"],
        "quizzes/05_by_value.c": ["inside=42", "outside=7"],
        "quizzes/06_rebind.c": ["local=9", "caller=7"],
        "answers/09_zero_buffer.c": ["zeroed=0,0,0", "null_empty=1", "null_nonempty=0"],
        "answers/10_poll_flag.c": ["ready=1", "idle=0", "zero_reads=0"],
    }
    if name == "examples/01_addresses.c":
        for key in ("CHAR_BIT", "sizeof_int", "sizeof_pointer"):
            match = re.search(rf"(?m)^{key}=(\d+)$", output)
            require(match is not None, f"实验 1 输出 {key}")
            metrics[key] = int(match.group(1))
        address = re.search(r"x_addr=(\S+) p_value=(\S+) p_addr=(\S+)", output)
        require(address is not None and address.group(1) == address.group(2), "实验 1 的初始 p 保存 x 的地址")
        require(lines[-3:] == ["initial: x=10 via_p=10 via_q=10", "write: x=20 via_q=20", "redirect: x=20 y=100 via_p=100 via_q=20"], "实验 1 的别名写入与改指向结果正确")
    elif name == "examples/02_arrays.c":
        width = metrics["sizeof_int"]
        expected_lines = ["count=4", f"array_bytes={4 * width} pointer_bytes={metrics['sizeof_pointer']} element_bytes={width}", f"whole_array_bytes={4 * width}", "step_equals_second=1", "sum=100", "empty_sum=0", "updated_sum=105"]
        require(lines == expected_lines, "实验 2 的数组大小、步长、显式长度与空输入结果正确")
    elif name == "quizzes/07_array_length.c":
        ratio = metrics["sizeof_pointer"] // metrics["sizeof_int"]
        require(lines == ["caller=4", f"callee={ratio}"], "自测 7 的错误长度与本机指针/元素大小比值一致")
    else:
        require(name in expected and lines == expected[name], f"输出符合预期：{name}")


def verify_links(paths: list[Path]) -> None:
    for path in paths:
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if re.match(r"(?:https?://|#)", link):
                continue
            target = path.parent / link.split("#", 1)[0]
            require(target.exists(), f"本地链接可定位：{path.name} -> {link}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialize", action="store_true", help="首次生成缺少的章节与源文件；不覆盖已有的不同内容")
    args = parser.parse_args()
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S_%f")
    run_dir = ROOT / "verification" / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    REPORT.update(started_at=datetime.now(timezone.utc).isoformat(), run_id=stamp,
                  primary=str(PRIMARY), python=sys.version, files={})
    report_path = run_dir / "verification.json"
    report_path.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "verification_latest.json").write_text(json.dumps({"status": "started", "run_id": stamp, "report": str(report_path.relative_to(ROOT))}, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        text = PRIMARY.read_text(encoding="utf-8")
        files, codes = generated_files(text)
        compare_or_materialize(files, args.materialize)
        compiler = shutil.which("gcc")
        require(compiler is not None, "PATH 中存在 GCC")
        version = invoke(["gcc", "--version"])
        target = invoke(["gcc", "-dumpmachine"])
        require(version["returncode"] == target["returncode"] == 0, "可读取 GCC 版本与目标")
        REPORT.update(compiler=compiler, compiler_version=version["stdout"].splitlines()[0], target=target["stdout"].strip(), platform_metrics={}, programs=[])
        flags = ["gcc", "-std=c11", "-Wall", "-Wextra", "-fdiagnostics-color=never"]
        for name, mode, _ in codes:
            executable = run_dir / (Path(name).stem + ".exe")
            compile_result = invoke(flags + [name, "-o", executable.relative_to(ROOT).as_posix()])
            require(compile_result["returncode"] == 0, f"C11 编译通过：{name}")
            if name == "quizzes/07_array_length.c":
                require("-Wsizeof-array-argument" in compile_result["stderr"], "自测 7 产生预期的数组形参 sizeof 警告")
            elif name == "quizzes/08_dangling.c":
                require("-Wreturn-local-addr" in compile_result["stderr"], "自测 8 产生预期的返回局部地址警告")
            else:
                require(not compile_result["stderr"].strip(), f"教学正确程序无编译诊断：{name}")
            item = {"source": name, "sha256": sha256(ROOT / name), "mode": mode, "compiled": True, "executed": False}
            REPORT["programs"].append(item)
            if mode == "run":
                result = invoke([str(executable)], timeout=10)
                require(result["returncode"] == 0 and not result["stderr"], f"运行正常退出：{name}")
                check_output(name, result["stdout"], REPORT["platform_metrics"])
                item.update(executed=True, output_verified=True)
            else:
                require(name == "quizzes/08_dangling.c", "未定义行为反例仅编译、不执行")
            print(f"PASS {name} ({mode})", flush=True)

        const_code = (ROOT / "examples/03_const.c").read_text(encoding="utf-8")
        for index, statement in enumerate(("*read_only = 7;", "fixed = &y;", "*fixed_read = 7;"), 1):
            variant = run_dir / f"const_rejected_{index}.c"
            marker = f"/* {statement} */"
            require(const_code.count(marker) == 1, f"const 变体 {index} 只修改一个预定语句")
            variant.write_text(const_code.replace(marker, statement), encoding="utf-8", newline="\n")
            result = invoke(flags + ["-fsyntax-only", variant.relative_to(ROOT).as_posix()])
            require(result["returncode"] != 0 and "read-only" in result["stderr"], f"非法 const 赋值 {index} 被 GCC 明确拒绝")

        optimized = run_dir / "04_volatile_O2.exe"
        result = invoke(flags + ["-O2", "examples/04_volatile.c", "-o", optimized.relative_to(ROOT).as_posix()])
        require(result["returncode"] == 0 and not result["stderr"], "实验 4 的 O2 版本编译无诊断")
        result = invoke([str(optimized)], timeout=10)
        require(result["returncode"] == 0 and not result["stderr"], "实验 4 的 O2 版本正常退出")
        check_output("examples/04_volatile.c", result["stdout"], REPORT["platform_metrics"])
        assembly_path = run_dir / "04_volatile_O2.s"
        result = invoke(flags + ["-O2", "-S", "examples/04_volatile.c", "-o", assembly_path.relative_to(ROOT).as_posix()])
        require(result["returncode"] == 0 and not result["stderr"], "实验 4 的汇编输出生成成功")
        assembly = assembly_path.read_text(encoding="utf-8")
        REPORT["assembly"] = {"path": str(assembly_path), "sha256": sha256(assembly_path), "observations": {}}
        for function, symbol in (("read_regular_twice", "regular_value"), ("read_observed_twice", "observed_value")):
            match = re.search(rf"(?ms)^{function}:\n(.*?)^\s*\.seh_endproc", assembly)
            if match:
                # AT&T 语法中源操作数在前；带内存源操作数的 add 同样读取内存。
                read_pattern = rf"^\s*(?:mov\w*|add\w*)\s+{re.escape(symbol)}\(%rip\),"
                read_lines = [line.strip() for line in match.group(1).splitlines() if re.search(read_pattern, line)]
                REPORT["assembly"]["observations"][function] = {"body": match.group(1), "memory_read_lines": read_lines, "count": len(read_lines)}
        # 这一观察器只识别本课的 x86-64 MinGW 汇编，不宣称适用于所有目标。
        if REPORT["target"] == "x86_64-w64-mingw32":
            observations = REPORT["assembly"]["observations"]
            require(observations.get("read_regular_twice", {}).get("count") == 1, "本机 O2 普通函数观察到一次相应内存读取")
            require(observations.get("read_observed_twice", {}).get("count") == 2, "本机 O2 易变函数观察到两次相应内存读取")
        verification_note = ROOT / "90_验证记录.md"
        require(verification_note.exists(), "生成来源与验证边界说明存在")
        verify_links([PRIMARY] + [path for path in files if path.suffix == ".md"] + [verification_note])
        REPORT["files"] = {str(path.relative_to(ROOT.parent)): sha256(path) for path in [PRIMARY, Path(__file__).resolve(), *files, verification_note]}
        REPORT.update(status="passed", programs_compiled=len(codes), safe_programs_executed=sum(mode == "run" for _, mode, _ in codes), unsafe_programs_executed=0, expected_const_rejections=3)
    except Exception as exc:
        REPORT.update(status="failed", failure_type=type(exc).__name__, failure=str(exc))
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
    finally:
        REPORT["finished_at"] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
        (ROOT / "verification_latest.json").write_text(json.dumps({"status": REPORT["status"], "run_id": stamp, "report": str(report_path.relative_to(ROOT)), "report_sha256": sha256(report_path)}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"RESULT={REPORT['status']} REPORT={report_path}", flush=True)
    return 0 if REPORT["status"] == "passed" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
