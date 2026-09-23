# RamenSOPs

The public registry of general-purpose **SOPs** (standard operating procedures) for
[Rameness](https://github.com/Prog-Ramen/Rameness): the JEV-driven agent harness.

An SOP is a tested, parameterised procedure an agent can run instead of re-deriving the same
steps. Rameness learns SOPs from repeated work, keeps them private by default, and only
general ones - reviewed privately, scanned for secrets - are released here.

## Layout

```
sops/
  index.json                 metadata-only index (discovery never downloads code)
  <category>/_node.json      category description, keywords, requirements
  <category>/<name>/sop.json interface: description, inputs (JSON schema), permissions, tests
  <category>/<name>/run.py   implementation: JSON args on stdin -> JSON result on stdout
```

## Use

```bash
rameness sop install https://github.com/Prog-Ramen/RamenSOPs
rameness sop remote "fetch json from an api"      # searches sops/index.json
rameness sop test                                  # runs every SOP's embedded tests
```

## Contribute

SOPs are not proposed here directly: a PR to a public repo is public as soon as it is pushed.
Rameness proposes SOPs to a private staging registry for review (`rameness sop propose`), then
`rameness sop release` re-scans merged SOPs and opens a release PR here. Every SOP must be
general (no organization-specific endpoints, names or data), contain no secrets, and pass its tests.
