# Project conventions

## Python copyright headers

- New Python files, including tests and `__init__.py`, must use the full project
  copyright and GPL header matching neighboring Python files and `.copyright.tmpl`.
- Include the separator lines, SPDX copyright notice, Johannes Kepler University
  attribution, KPEX project reference, full GPL notice, and SPDX license identifier.
- Follow `run_licenseheaders.sh` for the project owner and copyright year range.
- Do not substitute abbreviated SPDX-only headers. Preserve full headers when
  editing existing Python files.

## Python typing style

- Use type hints for function and method parameters and non-void return values.
- Use collection types from `typing`, such as `List[str]`, `Dict`, `Set`, and
  `Tuple`, rather than built-in generics such as `list[str]`, `dict`, `set`, and
  `tuple`.
- For functions and methods that return no value, omit the return annotation;
  do not write `-> None`.

## Scope

- One concern per branch; report unrelated findings instead of fixing them. FasterCap
  changes get their own PR. PDK fix branches stay data-only.
- No public API (protocols, entry-point groups, options, modules) without a caller and a
  test. Plugin API `v1` is provisional (colleagues are testing it) and may still change;
  once Martin declares it stable, breaking changes need a `v2`.
- Say in the commit body when behavior changes: CLI validation, return values, exit codes,
  `__all__`.
- Fix root causes in the shared code, not with special cases.

## Domain

- PDK-agnostic: no PDK names or special cases in Python; PDK data goes in the protobuf tech
  info (`scripts/gen_tech_pb`).
- Coefficients must make physical sense: identical stacks give identical values. Compare
  sibling variants; report inconsistent upstream data, don't copy it.
- FasterCap results depend on the platform: not a reference, and no re-baselining in
  unrelated work.
- MAGIC: `extract do resistance` already runs extresist; `extresist all` doesn't fix
  multi-port nets. Compare R with 2.5D effective resistances.

## Code

- Validate cheap inputs (CLI args, names) before loading or resolving; error messages list
  the valid values.
- Wrap third-party/plugin exceptions in the domain error (`from exc`, naming the source);
  don't re-label domain errors. One broken plugin must not break others.
- Validate option values, not just names (`'false'` ≠ `False`).
- Return the paths you wrote; never scan a directory for them (leftover files).
- Format-only paths must not import KLayout or generated protobuf: import lazily, and put
  type-only imports under `TYPE_CHECKING`.
- Docs describe contracts, not file layout.
- Don't duplicate code, test helpers included: share it in a module (e.g. `tests/common/`)
  rather than copying it, and extend the shared code rather than adding a variant.

## Tests

- Run tests in the poetry venv: `poetry run pytest -m "not slow and not smoke"` (or
  `poetry run pytest tests/<area> -q`) before calling work done; report failures with their
  output. `./run_unit_tests.sh` exits with the status of `open`, not of pytest.
- Per commit, run the unit tests and the tests of the changed area; run all tests but the
  smoke tests (`poetry run pytest -m "not smoke" -n 3`) once before handing over a PR, as
  CI runs no slow tests (extraction, simulators).
- CI runs the unit tests with Python 3.12 and the KLayout Python module only (no
  executable), on Linux, macOS and Windows: before handing over a PR, also run them with
  Python 3.12 (e.g. in IIC-OSIC-TOOLS) and with `KPEX_KLAYOUT_EXE=/nonexistent`.
- Each bug fix gets a test that fails without it. A test that needs a workaround means the
  code is wrong: fix the code.
- No loosened tolerances or re-baselined numbers without a physical explanation.
- Subprocess tests put the child's stderr in the assertion message.

## Git

- Martin reviews in detail and commits himself: leave changes uncommitted in the working
  copy. For a change that should become several commits, stage it and propose the split.
  Proposed commit messages are welcome as a starting point. Don't commit or push unless
  asked; never commit scratch files.
- Martin keeps WIP stashes: never chain `git stash push`/`pop`. Test staged changes via
  `git checkout-index -a --prefix=<dir>/` or a temporary worktree.
- Commit subject: `Area: verb phrase`, 6–12 words, no articles, e.g. `R Extractor: fix
  handling of resistance units`. Area is a component, file or PDK (`kpex CLI`, `KPEX/2.5D`,
  `sky130A LVS`); a short reason may go in parentheses. Usually no body; one or two lines
  for a non-obvious why or a behavior change.
- Commit and PR texts contain only what the reader can't get from the issue, diff or CI:
  the non-obvious why, rejected alternatives, behavior changes, risks. PR: issue reference
  plus 1–4 sentences, no Summary/Changes/Testing headings.
- Propose a PR title with every PR text, in the style of the commit subjects; for several
  commits, name what they have in common rather than repeating the first subject.
- Every PR references an issue: `Fixes #N` when it resolves the issue (GitHub closes it on
  merge), `Part of #N` when it covers only part of it. Without an issue, file one first.
- A PR is ready when its CI is green on its final commits: after each push, check the CI
  and report every red job with its cause.
- After rewriting a pushed branch, say that it must be pushed before the merge.
- Merge only green PRs: `main` stays green, as a red baseline hides new failures.
- Issues end with the versions used, e.g. `klayout-pex 0.4.4, KLayout 0.30.12,
  IIC-OSIC-TOOLS image 83ae1840458f`, plus the versions of the plugins involved. Give both
  KLayout versions when the binary and the Python module differ.
- Aim for the sweet spot, not minimal length: too terse makes the reader guess the why;
  repetition and self-justification make the reader parse and check sentences that add
  nothing.
- In commit bodies, PR texts, issues, comments and docs, prefer bullet lists to long
  sentences chained with semicolons: one fact per bullet, under a short lead-in such as
  `New commands:`. No period at the end of a bullet.
- Mark files, code, command line tools and their arguments as code with backticks, e.g.
  `tests/common/ngspice.py`, `convert_to_vacask`, `kpex --netlist-format vacask`.
- No AI attribution: no `Co-Authored-By` trailer, no "Generated with …" line.
- Before handing over, re-read your diff against `main` and check it against this file.
