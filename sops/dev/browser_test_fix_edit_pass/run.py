import json
import os
import re
import subprocess
import sys


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


def normalize_filter(failure_filter):
    failure_filter = (failure_filter or "^")
    if failure_filter.startswith("^"):
        failure_filter = failure_filter[1:]
    return failure_filter


def compile_filter(failure_filter):
    failure_filter = normalize_filter(failure_filter)
    try:
        return re.compile(failure_filter)
    except re.error as exc:
        fail("invalid failure_filter: %s" % exc)


def run_test(workdir, test_command, timeout):
    try:
        proc = subprocess.run(
            test_command,
            shell=True,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, ["TIMEOUT: test command exceeded %s seconds" % timeout]
    except FileNotFoundError as exc:
        fail("test command not found: %s" % exc)
    except OSError as exc:
        fail("test command failed to start: %s" % exc)
    lines = proc.stdout.splitlines() if proc.stdout is not None else []
    if proc.returncode != 0:
        lines.append("EXITCODE:%d" % proc.returncode)
        return False, lines
    return True, lines


def run_fix(workdir, cmd):
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        fail(
            "fix command failed (%d): %s | %s"
            % (
                proc.returncode,
                cmd,
                (proc.stderr or proc.stdout).strip()[:500],
            )
        )


def main():
    try:
        args = json.load(sys.stdin)
    except Exception as exc:
        fail("invalid JSON stdin: %s" % exc)

    workdir = args.get("workdir") or "."
    if not os.path.isdir(workdir):
        fail("workdir does not exist: %s" % workdir)

    test_command = args.get("test_command")
    if not test_command:
        fail("test_command is required")
    if isinstance(test_command, list):
        test_command = " ".join(str(x) for x in test_command)
    elif not isinstance(test_command, str):
        fail("test_command must be string or array of strings")

    timeout = args.get("timeout", 300)
    try:
        timeout = int(timeout)
    except Exception:
        fail("timeout must be integer")

    failure_filter = args.get("failure_filter") or "^  FAIL|FAILED|AssertionError"
    try:
        compiled = compile_filter(failure_filter)
    except SystemExit:
        raise

    max_attempts = int(args.get("max_attempts", 1))
    if max_attempts < 1:
        max_attempts = 1

    fix_commands = args.get("fix_commands") or []
    prepared_fixes = []
    for cmd in fix_commands:
        if isinstance(cmd, list):
            prepared_fixes.append(" ".join(str(x) for x in cmd))
        elif isinstance(cmd, str):
            prepared_fixes.append(cmd)
        else:
            fail("fix_commands must contain strings or arrays of strings")

    tail_chars = args.get("tail_chars")
    if tail_chars is not None:
        try:
            tail_chars = int(tail_chars)
        except Exception:
            tail_chars = None
        else:
            tail_chars = max(1, tail_chars)

    attempts = 0
    passed = False
    last_output = []
    failing_assertions = []

    while attempts < max_attempts:
        attempts += 1
        passed, last_output = run_test(workdir, test_command, timeout)
        matching = []
        for line in last_output:
            if compiled.search(line):
                if tail_chars:
                    line = line[:tail_chars]
                matching.append(line)
        failing_assertions = matching
        if passed:
            break
        if not prepared_fixes:
            break
        fix_index = min(attempts - 1, len(prepared_fixes) - 1)
        run_fix(workdir, prepared_fixes[fix_index])

    print(
        json.dumps(
            {
                "passed": bool(passed),
                "attempts": attempts,
                "failing_assertions": failing_assertions,
                "test_output_tail": last_output[-20:],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
