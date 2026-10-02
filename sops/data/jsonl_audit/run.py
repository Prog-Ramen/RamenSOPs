import json
import sys


def reject_constant(value):
    raise ValueError(f"Non-standard JSON constant: {value}")


def audit_text(text):
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]  # artifact of a trailing newline, not a physical line
    report = {
        "total_lines": len(lines),
        "object_count": 0,
        "blank_count": 0,
        "invalid_json_lines": [],
        "non_object_lines": [],
        "valid": None,
    }
    for lineno, raw in enumerate(lines, start=1):
        if raw.strip() == "":
            report["blank_count"] += 1
            continue
        try:
            value = json.loads(raw, parse_constant=reject_constant)
        except ValueError:
            report["invalid_json_lines"].append(lineno)
            continue
        if isinstance(value, dict):
            report["object_count"] += 1
        else:
            report["non_object_lines"].append(lineno)
    report["valid"] = (
        not report["invalid_json_lines"] and not report["non_object_lines"]
    )
    return report


def main():
    args = json.load(sys.stdin)
    text = args["text"]
    report = audit_text(text)
    if args.get("output_file"):
        with open(args["output_file"], "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    json.dump(report, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()