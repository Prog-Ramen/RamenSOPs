"""JavaScript syntax-check then tests SOP.

Reads a JSON object from stdin and prints one JSON object to stdout.
Fails non-zero with a message on stderr when a required syntax check or
test command fails.

The SOP uses `node --check` to syntax-check JavaScript sources, then runs
the requested test commands in the working directory. Per-command regular
expression filters and tail limits can be applied to captured output.

Only the Python standard library is used; external commands are invoked
through subprocess/shell.
"""
import glob
import json
import re
import subprocess
import sys
import os


def tail_lines(text, n):
    if n is None:
        return text
    lines = text.splitlines()
    if n == 0:
        return ""
    keep = lines[-n:] if len(lines) > n else lines
    return "\n".join(keep)


def filtered_tail(text, pattern, n):
    if pattern:
        rx = re.compile(pattern)
        text = "\n".join(line for line in text.splitlines() if rx.search(line))
    return tail_lines(text, n)


def normalize_sources(inputs):
    sources = inputs.get("sources")
    if sources is None:
        sources = ["js/*.js"]
    if isinstance(sources, str):
        sources = [sources]
    elif not isinstance(sources, list):
        raise ValueError("sources must be a list or string")
    out = []
    for item in sources:
        if not isinstance(item, str):
            raise ValueError("sources must contain strings")
        if not item:
            raise ValueError("sources must contain non-empty strings")
        out.append(item)
    return out


def resolve_sources(work_dir, patterns):
    files = []
    seen = set()
    for pat in patterns:
        matches = sorted(glob.glob(os.path.join(work_dir, pat), recursive=True))
        for m in matches:
            rp = os.path.realpath(m)
            if rp not in seen:
                files.append(m)
                seen.add(rp)
    return files


def run_checked_file(work_dir, path):
    command = ["node", "--check", path]
    proc = subprocess.run(command, cwd=work_dir, capture_output=True, text=True)
    stdout = filtered_tail(proc.stdout or "", None, None)
    stderr = filtered_tail(proc.stderr or "", None, None)
    return {
        "path": path,
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout": stdout,
        "stderr": stderr,
    }


def normalize_tests(inputs):
    tests = inputs.get("test_scripts", [])
    if isinstance(tests, str):
        tests = [tests]
    if not isinstance(tests, list):
        raise ValueError("test_scripts must be a list")
    norm = []
    default_filter = inputs.get("global_filter")
    default_tail = inputs.get("global_tail")
    for item in tests:
        if isinstance(item, str):
            cmd = item
            filt = default_filter
            tail = default_tail
        elif isinstance(item, dict):
            cmd = item.get("command")
            if cmd is None:
                raise ValueError("test_scripts objects require 'command'")
            filt = item.get("filter", default_filter)
            tail = item.get("tail", default_tail)
        else:
            raise ValueError("test_scripts must contain strings or objects")
        if not isinstance(cmd, str) or not cmd:
            raise ValueError("test_scripts command must be a non-empty string")
        if filt is not None and not isinstance(filt, str):
            raise ValueError("filter must be a string")
        if tail is not None and (not isinstance(tail, int) or tail < 0):
            raise ValueError("tail must be a non-negative integer")
        norm.append({"command": cmd, "filter": filt, "tail": tail})
    return norm


def run_test(work_dir, test):
    command = test["command"]
    proc = subprocess.run(command, cwd=work_dir, shell=True, capture_output=True, text=True)
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if stdout and stderr:
        combined = stdout + "\n" + stderr
    elif stdout:
        combined = stdout
    elif stderr:
        combined = stderr
    else:
        combined = ""
    filtered = filtered_tail(combined, test["filter"], test["tail"])
    return {
        "command": command,
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "output": filtered,
    }


def main():
    raw = sys.stdin.read()
    try:
        inputs = json.loads(raw)
    except Exception:
        print("invalid json on stdin", file=sys.stderr)
        return 2

    if not isinstance(inputs, dict):
        print("stdin must be a JSON object", file=sys.stderr)
        return 2

    work_dir = inputs.get("work_dir")
    if not isinstance(work_dir, str) or not work_dir:
        print("work_dir must be a non-empty string", file=sys.stderr)
        return 2
    if not os.path.isdir(work_dir):
        print("work_dir does not exist or is not a directory: %s" % work_dir, file=sys.stderr)
        return 2

    try:
        sources = normalize_sources(inputs)
        files = resolve_sources(work_dir, sources)
        checks = [run_checked_file(work_dir, path) for path in files]
        tests = normalize_tests(inputs)
        test_results = [run_test(work_dir, t) for t in tests]
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    failed_syntax = [c for c in checks if not c["passed"]]
    failed_tests = [t for t in test_results if not t["passed"]]
    status = "passed" if not failed_syntax and not failed_tests else "failed"
    result = {
        "status": status,
        "work_dir": os.path.realpath(work_dir),
        "checks": checks,
        "tests": test_results,
    }
    print(json.dumps(result))

    if status == "failed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
