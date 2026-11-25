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

- One concern per branch. File verified user-facing defects as issues after checking for
  duplicates. Fix unrelated defects in separate PRs. Closely related defects may share a PR
  when they need the same change. Reference every issue and use `Fixes #N` for each resolved
  issue. FasterCap changes get their own PR. PDK fix branches stay data-only.
- No public API (protocols, entry-point groups, options, modules) without a caller and a
  test. Plugin API `v1` is provisional (colleagues are testing it) and may still change;
  once Martin declares it stable, breaking changes need a `v2`.
- Settle public terminology before expanding a contract. Use full, descriptive names
  such as `Specification` rather than abbreviations such as `Spec`. Distinguish requested
  input specifications from generated cases and results. Keep that vocabulary consistent
  across schema types and fields, APIs, CLI examples, tests, documentation and PR text.
  When terminology changes, audit all of these surfaces together.
- Say in the commit body when behavior changes: CLI validation, return values, exit codes,
  `__all__`.
- Fix root causes in the shared code, not with special cases.
- Separate general contracts from feature-specific implementations. Before placing a type,
  schema, validation rule or helper, consider its meaning and likely consumers, not just the
  feature introducing it. Shared protocol capabilities belong at the protocol level;
  feature-specific files contain only that feature's semantics. Do not add abstractions
  solely for hypothetical reuse, or mix unrelated cleanup into the current change.

## Domain

- PDK-agnostic: no PDK names or special cases in Python; PDK data goes in the protobuf tech
  info (`scripts/gen_tech_pb`).
- Coefficients must make physical sense: identical stacks give identical values. Compare
  sibling variants; report inconsistent upstream data, don't copy it.
- FasterCap results depend on the platform: not a reference, and no re-baselining in
  unrelated work.
- MAGIC: `extract do resistance` already runs extresist; `extresist all` doesn't fix
  multi-port nets. Compare R with 2.5D effective resistances.

### Technical terminology

- Use established terminology for physical quantities, device models, extraction methods
  and process variation. Do not invent alternative names or use vague umbrella terms when
  a precise technical term exists
- Prefer maintained PDK specifications for process-specific meanings and open technical
  documentation for extraction concepts. Useful references include
  [OpenRCX documentation](https://openroad.readthedocs.io/en/latest/main/src/rcx/README.html),
  [SKY130 process criteria](https://skywater-pdk.readthedocs.io/en/main/rules/assumptions.html) and
  [GF180MCU electrical specifications](https://gf180mcu-pdk.readthedocs.io/en/latest/analog/spice/elec_specs/elec_specs.html)
- Verify unfamiliar or ambiguous terminology against a relevant primary source before
  introducing it. Record the reference near the definition when the interpretation is
  non-obvious. Do not call terminology "official" or "standard" without an applicable
  authoritative definition
- Name the actual concept: for example, sheet resistance, contact resistance, capacitance
  model, process-stack parameters or dimensional bias. Reserve "law" for an identified
  physical law or explicitly defined mathematical relationship, not an unspecified
  collection of parameters or assumptions
- Preserve distinctions between source data, assumptions, empirical models and physical
  equations. State what "validated", "calibrated" or "qualified" means and what evidence
  supports it. Agreement with a source table or numerical solver does not establish
  agreement with silicon measurements
- When a project-specific concept needs a new name, explain why existing terminology is
  insufficient, define its meaning and scope, and settle the name before expanding the
  interface. Do not present project-specific vocabulary as an industry convention
- Apply the chosen terminology consistently across schemas, APIs, CLI help, comments,
  tests, documentation, issues and PRs. Preserve historical quotations and source
  identifiers, explaining their terminology where necessary

## Code

- Preserve tool-version constraints as documentation of required upstream fixes and
  capabilities. Add an independently named constraint for each new requirement instead
  of replacing or deleting earlier entries, even when a newer minimum subsumes them.
  Retain their version bounds, reasons, severities, scopes and source references. If an
  earlier rationale proves incorrect, document the correction and its evidence explicitly
  rather than silently erasing the history or retaining an incorrect claim as current fact.
  Review the file history when changing existing constraints to catch earlier lost context
- Validate cheap inputs (CLI args, names) before loading or resolving; error messages list
  the valid values.
- Wrap third-party/plugin exceptions in the domain error (`from exc`, naming the source);
  don't re-label domain errors. One broken plugin must not break others.
- Validate option values, not just names (`'false'` ≠ `False`).
- Return the paths you wrote; never scan a directory for them (leftover files).
- In production library and application code, do not use module-level variables or mutable
  class attributes for runtime state or configuration. This rule does not apply to test cases
  or self-contained standalone scripts. Keep state on the owning instance or pass it
  explicitly. Expose behavior, extension hooks and capability declarations through typed
  methods. Use a class method when the contract is independent of an instance. Immutable named constants and enums
  may live at module scope. Apply this rule within the current change; unrelated existing
  sites belong in a separate refactoring.
- Prefer enums and named, typed constants for variant dispatch. Do not replace them with
  string literals from protobuf `WhichOneof`; keep field-name reflection at the
  serialization and validation boundaries.
- Dispatch intended to cover all supported variants must fail explicitly for an unhandled
  case, using `NotImplementedError` with the operation and offending value where appropriate.
  Name intentionally skipped variants explicitly. Invalid external input gets the domain
  validation error rather than being treated as an unimplemented operation.
- Apply these conventions within the current PR's scope. Improvements to older, unrelated
  dispatch sites belong in a separate PR; do not mix a repository-wide cleanup into a feature.
- Format-only paths must not import KLayout or generated protobuf: import lazily, and put
  type-only imports under `TYPE_CHECKING`.
- Text I/O names its encoding, as the locale's is `cp1252` on Windows: `open()`,
  `Path.read_text()`, `logging.FileHandler`, `subprocess` with `text=True`. `utf-8`, also for
  the output of other tools, with `errors='replace'` where it is only shown.
- Docs describe contracts, not file layout.
- Define every project-owned structured JSON file or interchange format in a protobuf
  schema first. JSON remains a supported human-readable encoding, using protobuf's JSON
  parser and serializer with generated message types. Do not invent independent formats
  through dictionary literals, hand-written field lists or ad hoc JSON validators.
  Reuse appropriate existing messages and keep shared contracts outside feature-specific
  schemas. Reject schema violations when reading input, and separately validate semantic
  constraints such as required values, supported enums, units and physical bounds.
  Apply this to new or changed contracts; migrate unrelated existing formats separately.
  Third-party JSON contracts remain defined by their external owner.
- Don't duplicate code, test helpers included: share it in a module (e.g. `tests/common/`)
  rather than copying it, and extend the shared code rather than adding a variant.

## Tests

- Run tests in the poetry venv: `poetry run pytest -m "not slow and not smoke"` (or
  `poetry run pytest tests/<area> -q`) before calling work done; report failures with their
  output. `./run_unit_tests.sh` exits with the status of `open`, not of pytest.
- Per commit, run the unit tests and the tests of the changed area; run all tests but the
  smoke tests (`poetry run pytest -m "not smoke" -n 3`) once before handing over a PR, as
  CI's slow tests (integration job) may fail without failing the run.
- Tests that simulate skip without `ngspice`, `Xyce` or `VACASK` on `PATH`, and CI has only
  `ngspice`, on Linux. IIC-OSIC-TOOLS has all three: run the skipped ones there before
  opening or merging a PR.
- The extraction tests start from the committed LVS databases of their designs
  (`testdata/lvsdb`, see `tests/common/lvsdb_fixtures.py`), not from LVS. A change of an LVS
  deck, a test layout or the KLayout version outdates them: running the tests with the
  KLayout executable rebuilds them (`poetry run python -m tests.common.lvsdb_fixtures`
  rebuilds all), commit them with the change. Without it (CI), outdated ones fail.
- CI runs the unit tests with Python 3.12 and the KLayout Python module only (no
  executable), on Linux, macOS and Windows: before handing over a PR, also run them with
  Python 3.12 (e.g. in IIC-OSIC-TOOLS) and with `KPEX_KLAYOUT_EXE=/nonexistent`. CI's
  `PYTHONWARNDEFAULTENCODING=1` makes text I/O without encoding fail the tests on every platform.
- Each issue resolved by a fix gets a regression test that fails without the fix, including
  when several related issues share a PR. Exercise the observable user problem rather than
  reproducing the implementation. A test that needs a workaround means the code is wrong:
  fix the code.
- Plan test cases from the contract before implementation. Identify valid and invalid
  equivalence classes, then use boundary-value analysis (Grenzwertanalyse): test just below,
  at and just above relevant limits. Consider empty inputs, zero, signs, minimum/maximum
  sizes, numeric precision, overflow and underflow where they affect the contract.
- Consider interactions and sequence effects as well as isolated inputs. Use decision tables
  for interacting options, state-transition or ordering tests for stateful behavior, and
  invariants or independent reference results where appropriate. Choose cases by risk and
  expected behavior, not by mirroring branches in the implementation.
- Explain why the selected corner cases matter in test comments or the review notes. Keep
  that reasoning concise and specific to the failure modes. Do not add a generic checklist
  or irrelevant edge cases to every test.
- For exploratory or large field-solver runs, reuse the existing resource guard.
  Verify a hard memory limit and disabled swap for the entire process tree before
  launching. If either limit cannot be verified, stop before solving.
- Start with a coarse mesh and run one solve at a time with `--jobs 1` and
  `--threads-per-job 1`. Keep sampled RSS and a wall-clock deadline as additional
  safeguards. Preserve the resource log and any result stopped by a limit.
- No loosened tolerances or re-baselined numbers without a physical explanation.
- Subprocess tests put the child's stderr in the assertion message.

## Git

- Martin reviews in detail and commits himself: leave changes uncommitted in the working
  copy. For a change that should become several commits, stage it and propose the split.
  Proposed commit messages are welcome as a starting point. Don't commit or push unless
  asked; never commit scratch files.
- Martin keeps WIP stashes: never chain `git stash push`/`pop`. Test staged changes via
  `git checkout-index -a --prefix=<dir>/` or a temporary worktree.
- Branch names describe the change. Do not include identifiers of the assistant, model,
  provider, or automation used to produce it, whether as a prefix, suffix, or elsewhere.
- Commit subject: `Area: verb phrase`, 6–12 words, no articles, e.g. `R Extractor: fix
  handling of resistance units`. Area is a component, file or PDK (`kpex CLI`, `KPEX/2.5D`,
  `sky130A LVS`); a short reason may go in parentheses. Usually no body; one or two lines
  for a non-obvious why or a behavior change.
- Commit and PR texts contain only what the reader can't get from the issue, diff or CI:
  the non-obvious why, rejected alternatives, behavior changes, risks. PR: issue reference
  plus 1–4 sentences, no Summary/Changes/Testing headings.
- Propose a PR title with every PR text, in the style of the commit subjects, but with
  identifiers in backticks, as the generated release notes copy it verbatim; for several
  commits, name what they have in common rather than repeating the first subject.
- Propose a label with every PR text, for its category in the generated release notes:
  `bug`, `enhancement`, `documentation` or `breaking-change`. The labeler adds the PDK.
- Every PR references an issue: `Fixes #N` when it resolves the issue (GitHub closes it on
  merge), `Part of #N` when it covers only part of it. Without an issue, file one first.
- Before creating an issue or PR in any repository outside the `iic-jku` GitHub
  organization, prepare the complete title and body locally and show Martin the draft
  and target repository. For a PR, also provide the proposed code diff for review.
  Create it only after Martin has reviewed and explicitly approved that specific item.
  General permission to investigate, fix a problem or coordinate upstream is not approval
  to publish an external issue or PR. The requirement to file verified defects does not
  override this review requirement.
- A PR is ready when its CI is green on its final commits: after each push, check the CI
  and report every red job with its cause.
- After rewriting a pushed branch, say that it must be pushed before the merge.
- Merge only green PRs: `main` stays green, as a red baseline hides new failures.
- After a successful merge, remove the fully merged local and remaining remote feature
  branches and their dedicated worktree without waiting for another request. Fetch the
  merge target and verify that every branch change is included; a deleted upstream or
  closed PR is not proof. Preserve all uncommitted, untracked and needed ignored work.
  Return a primary checkout to the merge target instead of deleting it. Use managed
  worktree archiving where applicable, respect ownership and protection guards, and
  report any retained branch or worktree with the verified reason.
- Issues end with the versions used, e.g. `kpex 0.12.0, KLayout 0.30.14,
  IIC-OSIC-TOOLS image 83ae1840458f`, plus the versions of the plugins involved. Give both
  KLayout versions when the binary and the Python module differ.
- Aim for the sweet spot, not minimal length: too terse makes the reader guess the why;
  repetition and self-justification make the reader parse and check sentences that add
  nothing.
- In replies, commit bodies, PR texts, issues, comments and docs, use short paragraphs
  for explanations and bullet lists for separate facts or steps. Do not pack several
  points into one long line separated by semicolons or periods. Keep one fact per bullet,
  under a short lead-in such as `New commands:`. No period at the end of a bullet.
- Mark identifiers as code with backticks: files, code, command line tools and their
  arguments, and the names of layers, device classes and models, PDKs and their variants,
  e.g. `tests/common/ngspice.py`, `convert_to_vacask`, `kpex --netlist-format vacask`,
  `TopMetal1`, `inductor3`, `sg13cmos5l`. Tick every mention, not only the first.
- No AI attribution in branch names, commit metadata, code, docs, PRs, issues or comments.
  Do not name the assistants, models or providers used to produce the work. No
  `Co-Authored-By` trailer or "Generated with …" line.
- Don't name proprietary solvers or protected company and product names, in code, docs,
  commit, PR and issue texts or comments: write "commercial tool A", "commercial tool B".
- Verify reported blockers before attributing a cause. Distinguish the observed error
  from a diagnosis and state uncertainty when the cause is not established. An open task
  registration is not proof of running work or a separate user chat. Check actual ownership
  and lifecycle state before claiming that another chat blocks worktree cleanup, and do not
  bypass an ownership guard merely because a registration appears stale.
- Before handing over, re-read your diff against `main` and check it against this file.
