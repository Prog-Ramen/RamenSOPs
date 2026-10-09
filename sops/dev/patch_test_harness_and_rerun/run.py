#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys


def emit(result):
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()


def fail(message, result=None):
    # Always emit a final JSON object to stdout, even when terminating on a
    # hard error. Exit with status 0 so the caller can parse the emitted JSON
    # instead of treating this as a raised process failure.
    if result is None:
        result = base_result(returncode=1, status="fail", error=message)
    sys.stderr.write("error: " + message + "\n")
    sys.stderr.flush()
    emit(result)
    sys.exit(0)


def base_result(returncode=None, status=None, error=None, stdout="", stderr="", timed_out=False, timeout_seconds=None):
    return {
        "ok": (returncode == 0) and (status == "pass") if returncode is not None and status is not None else False,
        "returncode": returncode,
        "status": status,
        "stdout_tail": stdout,
        "stderr_tail": stderr,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_bytes": len(stdout.encode("utf-8", errors="replace")),
        "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
        "stdout_line_count": len(stdout.splitlines()),
        "stderr_line_count": len(stderr.splitlines()),
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds if timeout_seconds is not None else 0,
        "patch_summary": [],
        "screenshot": None,
        "command": None,
        "cwd": None,
        "error": error,
    }


def load_args():
    raw = sys.stdin.read()
    if not raw.strip():
        fail("empty stdin; expected a JSON argument object")
    try:
        args = json.loads(raw)
    except Exception as exc:
        fail("invalid JSON on stdin: " + str(exc))
    if not isinstance(args, dict):
        fail("stdin JSON must be an object")
    return args


def require_string(name, value):
    if not isinstance(value, str) or not value:
        fail(name + " must be a non-empty string")
    return value


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except FileNotFoundError:
        fail("test script not found: " + path)
    except IsADirectoryError:
        fail("test script path is a directory: " + path)
    except PermissionError:
        fail("cannot read test script: " + path)
    except OSError as exc:
        fail("cannot read test script " + path + ": " + str(exc))


def write_text(path, text):
    tmp = path + ".soppatch.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except PermissionError:
        fail("cannot write test script: " + path)
    except OSError as exc:
        fail("cannot write test script " + path + ": " + str(exc))


def validate_edits(edits):
    if edits is None:
        edits = []
    if not isinstance(edits, list):
        fail("edits must be an array of objects")
    normalized = []
    for idx, edit in enumerate(edits):
        if not isinstance(edit, dict):
            fail("edits[%d] must be an object" % idx)
        old = edit.get("old")
        new = edit.get("new")
        count = edit.get("count", -1)
        required = edit.get("required")
        if required is None:
            required = edit.get("required_match", False)
        old = require_string("edits[%d].old" % idx, old)
        if not isinstance(new, str):
            fail("edits[%d].new must be a string" % idx)
        if isinstance(count, bool) or not isinstance(count, int) or count < -1:
            fail("edits[%d].count must be an integer >= -1" % idx)
        if required and count == 0:
            fail("edits[%d] is required but count is 0" % idx)
        normalized.append({
            "old": old,
            "new": new,
            "count": count,
            "required": bool(required),
        })
    return normalized


def apply_edits(text, edits):
    summaries = []
    cur = text
    for edit in edits:
        old = edit["old"]
        new = edit["new"]
        count = edit["count"]
        n = cur.count(old)
        if n == 0 and edit["required"]:
            message = "required replacement target missing: " + old[:120]
            result = base_result(returncode=1, status="fail", error=message)
            fail(message, result=result)
        if count == -1:
            effective = n
            cur = cur.replace(old, new)
        else:
            effective = min(n, count)
            cur = cur.replace(old, new, effective)
        summaries.append({
            "old": old,
            "new": new,
            "count": edit["count"],
            "required": edit["required"],
            "replaced": effective,
            "missing": n == 0,
        })
    return cur, summaries


def build_env(extra):
    env = os.environ.copy()
    if extra:
        if not isinstance(extra, dict):
            fail("env must be an object")
        for key, val in extra.items():
            if not isinstance(key, str):
                fail("env keys must be strings")
            if val is None:
                val = ""
            if not isinstance(val, str):
                fail("env values must be strings")
            env[key] = val
    return env


def run_command(rerun_cmd, cwd, timeout, env):
    argv = ["sh", "-lc", rerun_cmd]
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": env,
    }
    if cwd:
        if not os.path.isdir(cwd):
            fail("cwd does not exist: " + cwd)
        kwargs["cwd"] = cwd
    timed_out = False
    try:
        if timeout is None or timeout == 0:
            proc = subprocess.run(argv, **kwargs)
        else:
            proc = subprocess.run(argv, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc = subprocess.CompletedProcess(args=argv, returncode=124, stdout="", stderr="")
    except FileNotFoundError:
        fail("sh is not available for rerun_cmd")
    except PermissionError:
        fail("permission denied invoking sh for rerun_cmd")
    except OSError as exc:
        fail("could not run rerun_cmd: " + str(exc))
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    returncode = -1 if proc.returncode is None else int(proc.returncode)
    if timed_out:
        stderr += "\nsop: command timed out\n"
    return returncode, stdout, stderr, timed_out


def tail(text, tail_lines, max_bytes):
    truncated = False
    data = text.encode("utf-8", errors="replace")
    if max_bytes and len(data) > max_bytes:
        truncated = True
        data = data[-max_bytes:]
    text2 = data.decode("utf-8", errors="replace")
    if tail_lines is not None:
        lines = text2.splitlines()
        if len(lines) > tail_lines:
            truncated = True
            lines = lines[-tail_lines:]
            text2 = "\n".join(lines)
            if text2:
                text2 += "\n"
    return text2, truncated


def find_screenshot(stdout, stderr, pattern):
    if not pattern:
        return None
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        fail("invalid screenshot_pattern: " + str(exc))
    for text in (stdout, stderr):
        m = rx.search(text)
        if m:
            return m.group(1) if m.groups() else m.group(0)
    return None


def classify_status(returncode, stdout, stderr, pass_regex, fail_regex):
    combined = stdout + "\n" + stderr
    if pass_regex:
        try:
            if re.search(pass_regex, combined):
                return "pass"
        except re.error as exc:
            fail("invalid pass_regex: " + str(exc))
    if fail_regex:
        try:
            if re.search(fail_regex, combined):
                return "fail"
        except re.error as exc:
            fail("invalid fail_regex: " + str(exc))
    if "PASS" in combined:
        return "pass"
    if "FAIL" in combined:
        return "fail"
    return "pass" if returncode == 0 else "fail"


def main():
    args = load_args()

    script_path = require_string("script_path", args.get("script_path"))
    edits = validate_edits(args.get("edits"))
    rerun_cmd = require_string("rerun_cmd", args.get("rerun_cmd"))
    cwd = args.get("cwd")
    timeout = args.get("timeout")
    if timeout is not None:
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 0:
            fail("timeout must be an integer >= 0")
    env = args.get("env")
    output_filter = args.get("output_filter", {})
    if output_filter and not isinstance(output_filter, dict):
        fail("output_filter must be an object")

    src = read_text(script_path)
    patched, patch_summary = apply_edits(src, edits)
    if patched != src or edits:
        write_text(script_path, patched)

    out_env = build_env(env)
    returncode, stdout, stderr, timed_out = run_command(
        rerun_cmd,
        cwd if isinstance(cwd, str) else None,
        timeout,
        out_env,
    )

    tail_lines = None
    max_bytes = None
    pass_regex = None
    fail_regex = None
    screenshot_pattern = None
    if output_filter:
        tail_lines = output_filter.get("tail_lines")
        if tail_lines is not None:
            if isinstance(tail_lines, bool) or not isinstance(tail_lines, int) or tail_lines < 0:
                fail("output_filter.tail_lines must be an integer >= 0")
        max_bytes = output_filter.get("max_bytes")
        if max_bytes is not None:
            if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
                fail("output_filter.max_bytes must be an integer >= 0")
        pass_regex = output_filter.get("pass_regex")
        fail_regex = output_filter.get("fail_regex")
        screenshot_pattern = output_filter.get("screenshot_pattern")

    stdout_tail, stdout_truncated = tail(stdout, tail_lines, max_bytes)
    stderr_tail, stderr_truncated = tail(stderr, tail_lines, max_bytes)
    status = classify_status(returncode, stdout, stderr, pass_regex, fail_regex)
    screenshot = find_screenshot(stdout, stderr, screenshot_pattern)

    result = {
        "ok": (returncode == 0) and (status == "pass"),
        "returncode": returncode,
        "status": status,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "stdout_bytes": len(stdout.encode("utf-8", errors="replace")),
        "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
        "stdout_line_count": len(stdout.splitlines()),
        "stderr_line_count": len(stderr.splitlines()),
        "timed_out": timed_out,
        "timeout_seconds": timeout if timeout is not None else 0,
        "patch_summary": patch_summary,
        "screenshot": screenshot,
        "command": "sh -lc " + repr(rerun_cmd),
        "cwd": cwd if isinstance(cwd, str) else None,
        "error": None,
    }
    emit(result)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        # Emit a valid JSON failure object on stdout before exiting.
        emit(base_result(returncode=1, status="fail", error=str(exc)))
        sys.stderr.write("error: " + str(exc) + "\n")
        sys.exit(0)
