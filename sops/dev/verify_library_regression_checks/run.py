#!/usr/bin/env python3
import json
import subprocess
import sys


def parse_int(value, default):
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def run_command(command, cwd, timeout):
    if command is None:
        return None
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
        )
        return completed.returncode
    except Exception:
        return -1


def main():
    raw = sys.stdin.read()
    try:
        args = json.loads(raw)
    except Exception:
        sys.stderr.write("invalid JSON input\n")
        return 2

    if not isinstance(args, dict):
        sys.stderr.write("invalid JSON input: object expected\n")
        return 2

    test_command = args.get("test_command")
    inline_check_script = args.get("inline_check_script")
    issue_list = args.get("issue_list", [])
    if not isinstance(issue_list, list):
        issue_list = []

    timeout_seconds = parse_int(args.get("timeout_seconds"), 30)
    cwd = args.get("cwd")

    if not test_command:
        sys.stderr.write("test_command is required\n")
        return 2
    if not inline_check_script:
        sys.stderr.write("inline_check_script is required\n")
        return 2

    test_exit_code = run_command(test_command, cwd, timeout_seconds)
    inline_exit_code = run_command(inline_check_script, cwd, timeout_seconds)

    if test_exit_code is None or inline_exit_code is None:
        sys.stderr.write("missing required command\n")
        return 2

    ok = test_exit_code == 0 and inline_exit_code == 0
    if ok:
        passed_issues = list(issue_list)
        failed_issues = []
    else:
        passed_issues = []
        failed_issues = list(issue_list)

    print(json.dumps({
        "ok": ok,
        "test_exit_code": test_exit_code,
        "inline_exit_code": inline_exit_code,
        "passed_issues": passed_issues,
        "failed_issues": failed_issues,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
