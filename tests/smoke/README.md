<!--
--------------------------------------------------------------------------------
SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
Johannes Kepler University, Institute for Integrated Circuits.

This file is part of KPEX 
(see https://github.com/iic-jku/klayout-pex).

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
SPDX-License-Identifier: GPL-3.0-or-later
--------------------------------------------------------------------------------
-->
# Smoke Tests

Smoke tests check the **installed wheel**, not the source checkout.

Tests running from the checkout can't catch packaging bugs: there, all files are present
(and symlinks are followed), even if the wheel lacks them. For example, 47 of the
`ihp-sg13cmos5l` rule decks were missing from the wheel, so `kpex --pdk ihp-sg13cmos5l`
failed for every user, while all tests passed
([#210](https://github.com/iic-jku/klayout-pex/issues/210)).

## Concept

- The `installed_wheel` fixture ([conftest.py](conftest.py)) installs the wheel
  (given by `KPEX_SMOKE_TEST_WHEEL`) into a fresh venv, once per test session,
  and makes sure `klayout_pex` is imported from there (not from the checkout).
- Smoke tests run the console scripts of that venv (`kpex`, `netlist`, `pex25d`)
  as subprocesses, outside of the checkout and without `PYTHONPATH`.
- Each aspect gets its own module, e.g. [pdk_extraction_test.py](pdk_extraction_test.py).
- All tests of this directory are automatically marked `smoke` (like `slow` for integration tests),
  so they're selected with `-m smoke`, and excluded from the unit tests (`-m "not slow and not smoke"`).
  Without `KPEX_SMOKE_TEST_WHEEL`, they're skipped.

| Module                                           | Checks                                            |
|--------------------------------------------------|---------------------------------------------------|
| [pdk_extraction_test.py](pdk_extraction_test.py) | `kpex extract --2.5D` works for each bundled PDK |

## Running locally

```bash
./run_smoke_tests.sh
```

Like the other `run_*_tests.sh` scripts, this generates the Allure report into `build/allure-report`
(and opens it on macOS). Before, it rebuilds everything the wheel packages, so it's never outdated:

1. `./gen_tech_pb.sh`, for the generated protobuf modules (`klayout_pex_protobuf/**/*_pb2.py`)
   and the PDK tech info (`klayout_pex_protobuf/*_tech.pb.json`)
2. `poetry build --format wheel`, into `build/smoke-tests-dist/`
3. `pytest -m smoke`

Requirements:
- the poetry environment, including `grpcio-tools` (see [DEVELOPMENT.md](../../DEVELOPMENT.md))
- KLayout (on the `PATH`, or `KPEX_KLAYOUT_EXE`)
- network access (to install the wheel's dependencies into the venv)

To check an existing wheel instead (e.g. a CI artifact, or a release downloaded from PyPI):
```bash
KPEX_SMOKE_TEST_WHEEL=path/to/klayout_pex-<version>-py3-none-any.whl poetry run pytest -m smoke
```

## Adding a smoke test

1. Add a module `tests/smoke/<aspect>_test.py` (it's marked `smoke` automatically).
2. Request the `installed_wheel` fixture, and run console scripts with
   `installed_wheel.run(...)` (returns the completed process) or
   `installed_wheel.check_run(...)` (also asserts exit status 0).
3. Use the Allure parent suite `"Smoke Tests (installed wheel)"`, with a suite of its own.

```python
import allure

@allure.parent_suite("Smoke Tests (installed wheel)")
@allure.suite("Console scripts")
def test_console_scripts(installed_wheel, tmp_path):
    for script in ('kpex', 'netlist', 'pex25d'):
        installed_wheel.check_run(script, '--help', cwd=tmp_path)
```

Guidelines:
- Never test code imported into the test process: `import klayout_pex` there comes from
  the checkout. Importing is fine for test data only (e.g. the `PDK` enum to parametrize over).
- Keep them quick (seconds), as they gate publishing. Prefer `--2.5D` over FasterCap or MAGIC.
- Use `tmp_path` as working and output directory.
- New PDK: add a small design to `SMOKE_TEST_DESIGNS` in
  [pdk_extraction_test.py](pdk_extraction_test.py), otherwise its smoke test fails.

## CI

[smoke-tests.yml](../../.github/workflows/smoke-tests.yml) runs the smoke tests against the
wheel built on Ubuntu, which is the one published to PyPI.
Publishing waits for the smoke tests to pass (see [ci-cd.yml](../../.github/workflows/ci-cd.yml)).
