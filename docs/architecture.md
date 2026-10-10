# Architecture

**In brief:** RamenSOPs is a Git repository of tested procedures (SOPs) plus the CI that guards it. Proposals
arrive as pull requests (usually opened by Rameness), pass mechanical checks, isolated tests, secret scanning
and a model review, and merge at the exact commit that was checked. After every merge a sharded, columnar index
is published to the `registry` branch, which Rameness reads one small listing at a time.

## The whole flow

From a proposal to an SOP another agent can pull.

```mermaid
flowchart LR
    rameness["Rameness<br/>(proposal pipeline)"] -- "branch sop/&lt;id&gt;, PR to main" --> pr["Pull request"]
    pr --> check["sop-check<br/>mechanical review + tests<br/>in isolated containers"]
    pr --> scan["secret-scan<br/>pinned gitleaks"]
    check --> merge["sop-merge<br/>security + quality review,<br/>merge at the checked commit"]
    scan --> merge
    merge -- "eligible" --> main[("main<br/>SOPs only")]
    merge -- "risky / uncertain" --> maint(["Maintainer"])
    maint --> main
    merge -- "prohibited" --> closed(["Closed, branch cleaned up"])
    main --> index["registry-index<br/>builds the sharded,<br/>columnar index"]
    index --> reg[("registry branch<br/>SOPs + generated indexes")]
    reg -- "index.json, _index.json, _meta.json,<br/>then only the chosen SOP's files" --> clients["Rameness clients"]
```

## The tree and its files

SOPs live in a category tree; every level stays small, like a Dremel serving tree.

```mermaid
flowchart TB
    root["sops/<br/>index.json: top-level categories only<br/>+ aliases of moved SOPs"]
    root --> cat["&lt;category&gt;/<br/>_node.json: description, keywords, requires<br/>_index.json: its children (generated)"]
    cat --> sub["&lt;subcategory&gt;/ (when a category grows past 8)"]
    cat --> sop["&lt;name&gt;/"]
    sub --> sop2["&lt;name&gt;/"]
    sop --> files["sop.json: interface, permissions, tests<br/>run.py: JSON in on stdin, JSON out<br/>_meta.json: inputs, permissions, file hashes (generated)"]
    root --> aliases["_aliases.json: old SOP id to new id"]
```

* **Sharded:** a client fetches a category's listing only when it decides to look inside it.
* **Columnar:** a listing holds only what a client chooses by (id, description, keywords). The rest is in the
  SOP's `_meta.json`, fetched only for the SOPs a client picks, and pinned by its hash in the listing.
* **Small at every level:** no category holds more than 8 SOPs directly. A proposal that would push one over
  splits it into subcategories in the same PR; moved SOPs keep their old ids as aliases.

## sop-check: reviewing a proposal

Runs on every PR with the trusted copy of the CI from `main`; it reads the PR's files as data.

```mermaid
flowchart TB
    start(["PR opened or updated"]) --> resolve["Resolve the exact head commit<br/>(ci/resolve.py)"]
    resolve --> diff["Compare full snapshots base vs head<br/>(nothing hidden in intermediate commits)"]
    diff --> paths{"Paths"}
    paths -- "outside sops/" --> human1["Maintainer review"]
    paths -- "generated files<br/>(index.json, _index.json, _meta.json)" --> fail1["Fail"]
    paths -- "pure moves (same files, new id)" --> reorg["Reorganization: maintainer review,<br/>not counted as new SOPs"]
    paths -- "_node.json, _aliases.json" --> struct["Validate the small JSON they must be"]
    paths -- "SOP files" --> crit["Per SOP: id matches its path, description,<br/>input schema, declared permissions,<br/>standard-library imports, no dynamic execution"]
    crit --> tests["Test rules: 2-40 tests, each asserting values,<br/>output keys or an error; 2+ concrete values;<br/>distinct cases; declared, typed inputs;<br/>fixtures only at relative paths"]
    tests --> crowd{"A category it adds to<br/>now over 8?"}
    crowd -- "yes" --> fail2["Fail: split it in this PR"]
    crowd -- "no" --> run["Run every test in a fresh container:<br/>no network, read-only, non-root, 256 MB,<br/>fixtures built inside the sandbox,<br/>expected errors must fail"]
    run --> verdict(["ok / maintainer needed / fail"])
```

## sop-merge: deciding and merging

Runs after `sop-check` and `secret-scan` finish, and every 15 minutes; it never runs a PR's code.

```mermaid
flowchart TB
    open(["Each open PR"]) --> sec["Security assessment<br/>gitleaks + source policy +<br/>model review (Kev on the runner)"]
    sec -- "prohibited" --> close["Close the PR,<br/>clean up the branch"]
    sec -- "uncertain / unavailable" --> wait1["Maintainer review<br/>(no automatic merge)"]
    sec -- "clean" --> rev["Mechanical review again<br/>(static)"]
    rev --> draft{"Draft?"}
    draft -- "yes" --> skip(["Skipped"])
    draft -- "no" --> fresh{"Up to date with main,<br/>and both checks green<br/>for this exact commit?"}
    fresh -- "no" --> wait2["Waiting"]
    fresh -- "yes" --> quality["Quality review: useful, general,<br/>matches its description, tests cover it<br/>(Kev on the runner)"]
    quality -- "not approved" --> wait1
    quality -- "approved, low-risk permissions" --> merge["Merge at the checked commit<br/>(head SHA guard)"]
    merge --> idx(["registry-index runs"])
```

Eligible for automatic merge: Python SOPs with `compute`, `fs:read` or `fs:write` permissions. Anything with
`network`, `exec` or side effects, skills, composites, reorganizations and changes outside `sops/` need a
maintainer.

## registry-index: publishing

After every merge to `main` (and hourly), `ci/index.py` builds the indexes without importing any SOP code and
force-publishes `sops/` with them to the `registry` branch, which is what Rameness reads.

```mermaid
sequenceDiagram
    participant M as main
    participant I as ci/index.py
    participant R as registry branch
    participant C as Rameness client
    M->>I: sops/ tree
    I->>I: per category: _index.json (id, description, keywords)
    I->>I: per SOP: _meta.json (inputs, permissions, file hashes)
    I->>R: SOPs + indexes, one commit per main revision
    C->>R: index.json, then only the listings it explores
    C->>R: _meta.json of the SOPs it picks (hash-checked)
    C->>R: those SOPs' files (each hash-checked), then runs their tests
```

## Code map

```
ci/
  review.py       mechanical review: paths, metadata, permissions, test rules, moves, crowding; runs tests in containers
  run_test.py     container-side test runner: builds fixtures, runs the SOP, checks expected errors and written files
  resolve.py      the exact PR head to review
  security.py     secret scan + source policy + model security review; closes prohibited PRs
  semantic.py     quality review (usefulness, generality, implementation, coverage)
  kev_*.py        runner-local Kev: setup, pinned weights, server, readiness, reviews, benchmark
  merge.py        the merge loop: re-check each open PR, merge eligible ones at their checked commit
  index.py        sharded, columnar index builder (no SOP code is imported)
tests/            tests of the CI itself
sops/             the SOPs
.github/workflows/
  sop-check.yml        review + container tests on every PR
  secret-scan.yml      pinned gitleaks on every PR and push
  sop-merge.yml        security + quality review and merge
  registry-index.yml   publish the registry branch
  kev-benchmark.yml    benchmark the CI's Kev when its setup changes
```

The client side (how Rameness proposes, places and pulls SOPs) is described in
[Rameness' architecture](https://github.com/Prog-Ramen/Rameness/blob/main/docs/architecture.md).
