"""Write the registry's metrics in the Prometheus text format, published with the index on the `registry` branch.

    python ci/metrics.py [--commit SHA] [--open-prs N] [--out metrics]

Prometheus scrapes the published file straight from GitHub (see README, "Monitoring"). Reads only the SOPs'
sop.json files; never imports or runs SOP code.
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

HELP = {
    "ramensops_sops": "SOPs in the registry, by top-level category, status and kind.",
    "ramensops_sop_tests": "Tests shipped with the registry's SOPs, by top-level category.",
    "ramensops_sops_requiring": "SOPs that need a permission, by permission.",
    "ramensops_open_pull_requests": "Open pull requests (proposed SOPs and changes) when the registry was built.",
    "ramensops_build_timestamp_seconds": "When the registry was built (Unix time).",
    "ramensops_build_info": "The commit of main the registry was built from.",
}


def esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def collect(root: Path) -> dict[str, list[tuple[dict, float]]]:
    sops, tests, perms = Counter(), Counter(), Counter()
    for meta in sorted(root.rglob("sop.json")):
        m = json.loads(meta.read_text())
        category = meta.relative_to(root).parts[0]
        sops[(category, m.get("status", "?"), m.get("kind", "?"))] += 1
        tests[category] += len(m.get("tests") or [])
        for p in m.get("permissions") or []:
            perms[p] += 1
    return {
        "ramensops_sops": [({"category": c, "status": s, "kind": k}, n) for (c, s, k), n in sorted(sops.items())],
        "ramensops_sop_tests": [({"category": c}, n) for c, n in sorted(tests.items())],
        "ramensops_sops_requiring": [({"permission": p}, n) for p, n in sorted(perms.items())],
    }


def render(samples: dict[str, list[tuple[dict, float]]]) -> str:
    out = []
    for name, rows in samples.items():
        out += [f"# HELP {name} {HELP[name]}", f"# TYPE {name} gauge"]
        for labels, value in rows:
            lab = ",".join(f'{k}="{esc(v)}"' for k, v in labels.items())
            out.append(f"{name}{{{lab}}} {value}" if lab else f"{name} {value}")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="sops")
    ap.add_argument("--commit", default="")
    ap.add_argument("--open-prs", type=int, default=None)
    ap.add_argument("--out", default="metrics")
    a = ap.parse_args()
    samples = collect(Path(a.root))
    if a.open_prs is not None:
        samples["ramensops_open_pull_requests"] = [({}, a.open_prs)]
    samples["ramensops_build_timestamp_seconds"] = [({}, int(time.time()))]
    samples["ramensops_build_info"] = [({"commit": a.commit[:12]}, 1)]
    Path(a.out).write_text(render(samples))


if __name__ == "__main__":
    main()
