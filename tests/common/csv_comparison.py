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

import io
import json

import allure
import csv_diff


def assert_csv_matches_expected(csv_path: str, expected_csv_content: str):
    """
    Compares the extracted netlist CSV with the expected one, by device,
    and attaches both and their differences to the allure report
    """
    allure.attach.file(csv_path, name='pex_obtained.csv', attachment_type=allure.attachment_type.CSV)
    allure.attach(expected_csv_content, name='pex_expected.csv', attachment_type=allure.attachment_type.CSV)

    expected_csv = csv_diff.load_csv(io.StringIO(expected_csv_content), key='Device')
    with open(csv_path, 'r', encoding='utf-8') as f:
        obtained_csv = csv_diff.load_csv(f, key='Device')
    diff = csv_diff.compare(expected_csv, obtained_csv, show_unchanged=False)
    human_diff = csv_diff.human_text(
        diff, current=obtained_csv, extras=(('Net1', '{Net1}'), ('Net2', '{Net2}'))
    )
    allure.attach(json.dumps(diff, sort_keys=True, indent='    ').encode("utf8"),
                  name='pex_diff.json', attachment_type=allure.attachment_type.JSON)
    allure.attach(human_diff.encode("utf8"), name='‼️ pex_diff.txt', attachment_type=allure.attachment_type.TEXT)
    assert human_diff == '', 'Diff detected'
