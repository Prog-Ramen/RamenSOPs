import json, os, subprocess, sys


def _root(args):
    root = args.get("root", ".")
    if not os.path.isdir(root):
        raise ValueError("root directory does not exist: " + root)
    return root


def _package_env(args):
    env = os.environ.copy()
    package_path = args.get("package_path", ".")
    if not package_path:
        return env

    package_abspath = os.path.abspath(package_path)
    candidates = []
    if package_path == ".":
        candidates.append(os.getcwd())
    else:
        candidates.append(package_abspath)
        candidates.append(os.path.dirname(package_abspath))

    seen = set()
    cwd = os.getcwd()
    final_candidates = []
    for candidate in candidates:
        normalized = os.path.abspath(candidate)
        if normalized in seen or normalized == cwd:
            continue
        if os.path.isdir(normalized):
            seen.add(normalized)
            final_candidates.append(normalized)

    if final_candidates:
        if env.get("PYTHONPATH"):
            env["PYTHONPATH"] = os.pathsep.join(final_candidates + [env["PYTHONPATH"]])
        else:
            env["PYTHONPATH"] = os.pathsep.join(final_candidates)
    return env


def _run_python(args, code=None, script=None, argv=None, cwd=None, timeout=120):
    env = _package_env(args)
    cmd = [sys.executable]
    if code is not None:
        cmd.extend(["-c", code])
    elif script is not None:
        if not os.path.isfile(script):
            raise ValueError("check script does not exist: " + script)
        cmd.append(script)
    else:
        raise ValueError("issue check needs either `code` or `script`")
    if argv:
        cmd.extend(argv)
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return {
        "exitcode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def _run_suite(args, timeout=120):
    root = _root(args)
    env = _package_env(args)
    suite_command = args.get("suite_command")
    if suite_command:
        proc = subprocess.run(["sh", "-c", suite_command], cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
        return {
            "command": suite_command,
            "exitcode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    tests_dir = args.get("tests_dir", "tests")
    top_level_dir = args.get("top_level_dir", ".")
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", tests_dir, "-t", top_level_dir]
    proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
    return {
        "command": " ".join(cmd),
        "exitcode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def _check(args, check, timeout=120):
    name = check.get("name")
    if not name:
        raise ValueError("issue check is missing `name`")
    cwd = check.get("cwd", ".")
    if cwd:
        if not os.path.isdir(cwd):
            raise ValueError("check cwd does not exist: " + cwd)
    else:
        cwd = "."
    try:
        result = _run_python(args, code=check.get("code"), script=check.get("script"), argv=check.get("argv"), cwd=cwd, timeout=timeout)
    except ValueError as exc:
        return {"name": name, "passed": False, "exitcode": -1, "stdout": "", "stderr": str(exc)}
    except Exception as exc:
        return {"name": name, "passed": False, "exitcode": -1, "stdout": "", "stderr": str(exc)}
    result["name"] = name
    result["passed"] = result["exitcode"] == 0
    return result


def main():
    args = json.load(sys.stdin)
    if not isinstance(args, dict):
        raise ValueError("stdin must be a JSON object")
    if "package_path" not in args:
        raise ValueError("missing required argument: package_path")
    checks = args.get("issue_checks", [])
    if not isinstance(checks, list):
        raise ValueError("issue_checks must be a list")
    timeout = int(args.get("timeout", 120))
    max_attempts = int(args.get("max_attempts", 1))
    if max_attempts < 1:
        max_attempts = 1
    if max_attempts > 10:
        max_attempts = 10

    last = None
    attempts_used = 0
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        suite = _run_suite(args, timeout=timeout)
        check_results = [_check(args, check, timeout=timeout) for check in checks]
        passed = suite["exitcode"] == 0 and all(result["passed"] for result in check_results)
        last = {
            "passed": passed,
            "attempts": attempts_used,
            "suite": suite,
            "issue_checks": check_results,
        }
        if passed:
            break
    print(json.dumps(last))


if __name__ == "__main__":
    main()
