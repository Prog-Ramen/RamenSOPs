import json
import os
import re
import sys
import glob
import subprocess


def emit(obj):
    print(json.dumps(obj))


def fail(message):
    sys.stderr.write(str(message) + "\n")
    sys.exit(1)


def read_args():
    raw = sys.stdin.read()
    if not raw.strip():
        fail("missing JSON argument object")
    try:
        args = json.loads(raw)
    except Exception as e:
        fail("invalid JSON: %s" % e)
    if not isinstance(args, dict):
        fail("argument JSON must be an object")
    return args


def validate_args(args):
    js_files = args.get("js_files")
    if js_files is None:
        js_files = ["*.js"]
    if not isinstance(js_files, list):
        fail("js_files must be a list")
    for item in js_files:
        if not isinstance(item, str) or not item:
            fail("js_files must contain non-empty strings")
    unit_test_path = args.get("unit_test_path")
    if not isinstance(unit_test_path, str) or not unit_test_path:
        fail("unit_test_path must be a non-empty string")
    tail = args.get("tail", 8)
    if isinstance(tail, bool):
        fail("tail must be an integer")
    if not isinstance(tail, int):
        try:
            tail = int(tail)
        except Exception:
            fail("tail must be an integer")
    if tail < 0:
        fail("tail must be >= 0")
    node_path = args.get("node_path", "node")
    if node_path is None:
        node_path = "node"
    if not isinstance(node_path, str) or not node_path:
        fail("node_path must be a non-empty string")
    return js_files, unit_test_path, tail, node_path


def display_path(path):
    try:
        rel = os.path.relpath(path)
        if rel != os.curdir:
            return rel
        return path
    except Exception:
        return path


def collect_js_files(patterns, unit_test_path):
    seen = set()
    out = []
    try:
        unit_abspath = os.path.abspath(unit_test_path)
    except Exception:
        unit_abspath = None
    for pattern in patterns:
        if os.path.exists(pattern) and os.path.isfile(pattern):
            abspath = os.path.abspath(pattern)
            if abspath != unit_abspath and abspath not in seen:
                seen.add(abspath)
                out.append(abspath)
            continue
        matches = sorted(glob.glob(pattern, recursive=True))
        for path in matches:
            abspath = os.path.abspath(path)
            if os.path.isfile(abspath) and abspath != unit_abspath and abspath not in seen:
                seen.add(abspath)
                out.append(abspath)
    return out


def resolve_node(node_path):
    if os.path.isfile(node_path):
        if os.access(node_path, os.X_OK):
            return node_path
        return None
    if node_path != "node":
        return shutil.which(node_path)
    return "node"


def concise_syntax_error(message):
    message = (message or "").strip()
    if not message:
        return "syntax check failed"
    match = re.search(r"SyntaxError:\s*(.+)", message)
    if match:
        reason = match.group(1).strip()
        if len(reason) > 120:
            reason = reason[:120]
        return "SyntaxError: %s" % reason
    first = message.splitlines()[0].strip()
    if len(first) > 120:
        first = first[:120]
    return first or "syntax check failed"


def syntax_check_with_node(files):
    results = {}
    for path in files:
        try:
            proc = subprocess.run(
                ["node", "--check", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except Exception as e:
            return None, {path: concise_syntax_error(str(e))}
        if proc.returncode == 0:
            results[path] = None
        else:
            raw = proc.stderr.decode("utf-8", "replace")
            raw = raw or proc.stdout.decode("utf-8", "replace")
            results[path] = concise_syntax_error(raw)
    return "node --check", results


def stdlib_syntax_check(files):
    results = {}
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            results[path] = "read failed: %s" % e
            continue
        if text.lstrip().startswith("<"):
            results[path] = "not a JavaScript file (HTML/XML content)"
            continue
        if text.lstrip().startswith("#"):
            results[path] = "not a JavaScript file (hashbang)"
            continue
        code = text
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
        code = re.sub(r"//.*", "", code)
        code = code.replace('"', "")
        code = code.replace("'", "")
        code = re.sub(r"`.*?`", "", code, flags=re.DOTALL)
        code = re.sub(r"/\S*/", "", code)
        depth = 0
        for ch in code:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            if depth < 0:
                results[path] = "unbalanced braces outside strings/comments"
                break
        else:
            if depth != 0:
                results[path] = "unbalanced braces outside strings/comments"
            else:
                results[path] = None
    return "stdlib-regex", results


def run_unit_test(path):
    if not os.path.isfile(path):
        return False, None, ["missing unit test file: %s" % path], 1
    try:
        proc = subprocess.run(
            ["node", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception as e:
        return False, None, [str(e)], 1
    output = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    lines = [line for line in output.splitlines() if line.strip()]
    return proc.returncode == 0, proc.returncode, lines, len(lines)


def tail_lines(lines, n):
    if n <= 0:
        return []
    return lines[-n:]


def main():
    args = read_args()
    js_files, unit_test_path, tail, node_path = validate_args(args)
    files = collect_js_files(js_files, unit_test_path)
    if not files:
        fail("no JavaScript files matched: %s" % ", ".join(js_files))

    method, node_results = syntax_check_with_node(files)
    if method is not None:
        syntax_errors = {display_path(path): msg for path, msg in node_results.items() if msg}
        syntax_failed = sorted([display_path(path) for path, msg in node_results.items() if msg])
        syntax_ok = not syntax_failed
    else:
        method, stdlib_results = stdlib_syntax_check(files)
        syntax_errors = {display_path(path): msg for path, msg in stdlib_results.items() if msg}
        syntax_failed = sorted(list(syntax_errors.keys()))
        syntax_ok = not syntax_failed

    test_pass, test_exit_code, test_lines, test_output_full_lines = run_unit_test(unit_test_path)
    test_tail = tail_lines(test_lines, tail)

    result = {
        "syntax_ok": syntax_ok,
        "syntax_checked": [display_path(path) for path in files],
        "syntax_failed": syntax_failed,
        "syntax_errors": syntax_errors,
        "syntax_method": method,
        "test_path": display_path(os.path.abspath(unit_test_path)),
        "test_pass": test_pass,
        "test_exit_code": test_exit_code,
        "test_output_tail": test_tail,
        "test_output_full_lines": test_output_full_lines,
    }
    emit(result)


if __name__ == "__main__":
    main()
