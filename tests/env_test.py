#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
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

from __future__ import annotations

import allure
import os
from typing import *
import unittest

from klayout_pex.env import Env, EnvVar


@allure.parent_suite("Unit Tests")
@allure.tag("Env", "Environment", "Environmental Variables")
class Test(unittest.TestCase):
    def test_env_has_defaults(self):
        # ensure env is unset
        for var in EnvVar:
            if var.value in os.environ:
                del os.environ[var.value]

        env = Env.from_os_environ()

        for var in EnvVar:
            val = env[var]
            self.assertNotEqual('', val, f"Env must have a non-empty default for every variable, "
                                f"but {var.value} has none!")

    def test_env_with_custom_variables(self):
        def value_for_var(var: EnvVar) -> str:
            return f"{var.value}_is_set"

        # ensure env is unset
        for var in EnvVar:
            os.environ[var.value] = value_for_var(var)

        env = Env.from_os_environ()

        for var in EnvVar:
            val = env[var]
            self.assertEqual(value_for_var(var), val,
                             f"Envrionmental variable {var.value} was set to '{value_for_var(var)}', "
                             f"but Env['{var.value}'] returns '{val}'!")
