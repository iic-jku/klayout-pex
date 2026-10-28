#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX
# (see https://github.com/iic-jku/klayout-pex).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
# --------------------------------------------------------------------------------
#

"""
The files an installed kpex needs at runtime are packaged, checked on the checkout without building a wheel,
like the smoke tests do on the installed wheel (e.g. #210, where the wheel lacked the symlinked rule decks)
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import re
import tomllib
from typing import *

import allure
import pytest

from klayout_pex.pdk_config import PDK
from tests.common.build_scripts import REPO_DIR, kpex_symlinks

parent_suite = "Unit Tests"
tags = ("Packaging", "Wheel")

INCLUDE_PATTERN = re.compile(r'^\s*#\s*%include\s+(\S+)')


def pyproject() -> Dict[str, Any]:
    with open(os.path.join(REPO_DIR, 'pyproject.toml'), 'rb') as f:
        return tomllib.load(f)


def wheel_includes() -> Set[str]:
    """
    The files that the include of [tool.poetry] adds to the wheel, besides its packages
    (e.g. the generated ones, which .gitignore would leave out)
    """
    paths: Set[str] = set()
    for entry in pyproject()['tool']['poetry']['include']:
        if isinstance(entry, dict) and 'wheel' in entry.get('format', []):
            paths.add(entry['path'])
    return paths


def deck_files(deck_path: str) -> List[str]:
    """
    The LVS deck and the files it includes (%include of KLayout's preprocessor, relative to the including file),
    recursively

    :raises AssertionError: if an included file is missing
    """
    files = [deck_path]
    with open(deck_path, encoding='utf-8') as f:
        for line in f:
            match = INCLUDE_PATTERN.match(line)
            if match is None:
                continue
            included_path = os.path.join(os.path.dirname(deck_path), match.group(1))
            assert os.path.isfile(included_path), f"{deck_path} includes {match.group(1)}, which is missing"
            files += deck_files(included_path)
    return files


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_generated_protobuf_modules_are_in_the_wheel():
    protos_dir = Path(REPO_DIR, 'protos')
    modules = {f"klayout_pex_protobuf/{proto.relative_to(protos_dir).with_suffix('').as_posix()}_pb2.py"
               for proto in protos_dir.rglob('*.proto')}
    assert sorted(modules - wheel_includes()) == []


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk', list(PDK), ids=str)
def test_tech_info_of_each_pdk_is_in_the_wheel(pdk: PDK):
    assert f"klayout_pex_protobuf/{os.path.basename(pdk.config.tech_pb_json_path)}" in wheel_includes()


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('pdk', list(PDK), ids=str)
def test_lvs_deck_of_each_pdk_and_its_includes_are_in_the_wheel(pdk: PDK):
    # NOTE: within pdk/, which the wheel has as klayout_pex/pdk (see the packages of [tool.poetry])
    pdk_dir = os.path.join(REPO_DIR, 'pdk')
    for path in deck_files(pdk.config.pex_lvs_script_path):
        assert os.path.commonpath([os.path.abspath(path), pdk_dir]) == pdk_dir, path


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
def test_symlinks_within_the_packages_can_be_packaged():
    # NOTE: the build backend packages a symlinked file as a regular file, and refuses dangling or chained symlinks,
    #       or those that point outside of the project (see scripts/build/kpex_symlinks.py)
    symlinks = kpex_symlinks()
    package_dirs = symlinks.poetry_package_dirs(Path(REPO_DIR))
    assert symlinks.find_symlinks(Path(REPO_DIR), package_dirs) != []  # e.g. the shared IHP rule decks


@allure.parent_suite(parent_suite)
@allure.tag(*tags)
@pytest.mark.parametrize('script', sorted(pyproject()['project']['scripts']))
def test_console_script_has_its_entry_point(script: str):
    module_name, function_name = pyproject()['project']['scripts'][script].split(':')
    module = importlib.import_module(module_name)
    assert callable(getattr(module, function_name, None)), f"{script}: no {function_name} in {module_name}"
