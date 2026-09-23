# RamenSOPs

The public registry of general-purpose **SOPs** (standard operating procedures) for
[Rameness](https://github.com/Prog-Ramen/Rameness): the JEV-driven agent harness.

An SOP is a tested, parameterised procedure an agent can run instead of re-deriving the same
steps. Rameness learns SOPs from repeated work, keeps them private by default, and only
general ones - reviewed privately, scanned for secrets - are released here.

## Layout

```
sops/
  index.json                   top-level categories only
  <category>/_index.json       that category's children: sub-categories, and SOPs with
                               metadata + per-file SHA-256 (no code)
  <category>/_node.json        category description, keywords, requirements
  <category>/<name>/sop.json   interface: description, inputs (JSON schema), permissions, tests
  <category>/<name>/run.py     implementation: JSON args on stdin -> JSON result on stdout
```

The index is sharded so clients never download the whole registry.

## Use

Rameness pulls from this registry on its own, and only what a task needs. When no local SOP
covers a task, JEV walks this tree lazily with its normal activation criteria: it fetches a
category's `_index.json` only when it explores that branch, downloads only the SOPs it selects,
verifies every file's hash, and keeps an SOP only if its tests pass. SOPs that need permissions
beyond your allowed set are pulled only with your approval.

```bash
rameness sop pull text.slugify      # pull one SOP (walks only its ancestors' listings)
rameness sop remote "slugify a title"
```

## Contribute

SOPs are not proposed here directly: a PR to a public repo is public as soon as it is pushed.
Rameness proposes SOPs to a private staging registry for review (`rameness sop propose`), then
`rameness sop release` re-scans merged SOPs and opens a release PR here. Every SOP must be
general (no organization-specific endpoints, names or data), contain no secrets, and pass its tests.
