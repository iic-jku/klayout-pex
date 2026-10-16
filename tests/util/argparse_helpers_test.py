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
from enum import StrEnum, IntEnum
from typing import *
import unittest

import argparse
import contextlib
import io
from unittest import mock

from klayout_pex.log import LogLevel
from klayout_pex.util.argparse_helpers import (
    add_argument_with_former_name,
    add_log_level_argument,
    render_enum_help,
    true_or_false,
    warn_deprecated_options,
)


@allure.parent_suite("Unit Tests")
@allure.tag("Enum", "Help", "Util")
class Test(unittest.TestCase):
    def test_render_enum_help__nodefault__intenum(self):
        class IntEnum1(IntEnum):
            CASE1 = 1
            CASE2 = 2

        expected_string = "--arg ∈ {'case1', 'case2'}"
        obtained_string = render_enum_help(enum_cls=IntEnum1, topic="--arg", print_default=False)
        assert obtained_string == expected_string

    def test_render_enum_help__default__intenum(self):
        class IntEnum2(IntEnum):
            CASE1 = 1
            CASE2 = 2
            DEFAULT = CASE1

        expected_string = "--arg ∈ {'case1', 'case2'}.\nDefaults to 'case1'"
        obtained_string = render_enum_help(enum_cls=IntEnum2, topic="--arg", print_default=True)
        assert obtained_string == expected_string

    def test_render_enum_help__default__strenum(self):
        class StrEnum1(StrEnum):
            CASE1 = "Case1"
            CASE2 = "Case2"
            DEFAULT = CASE1

        expected_string = "--arg ∈ {'Case1', 'Case2'}.\nDefaults to 'Case1'"
        obtained_string = render_enum_help(enum_cls=StrEnum1, topic="--arg", print_default=True)
        assert obtained_string == expected_string

    def test_render_enum_help__default__strenum__lowercased(self):
        class StrEnum1(StrEnum):
            CASE1 = "Case1"
            CASE2 = "Case2"
            DEFAULT = CASE1

        expected_string = "--arg ∈ {'case1', 'case2'}.\nDefaults to 'case1'"
        obtained_string = render_enum_help(enum_cls=StrEnum1, topic="--arg",
                                           print_default=True,
                                           lowercase_strenum=True)
        assert obtained_string == expected_string


def parser_with_former_names(required: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='tool')
    group = parser.add_argument_group('Output')
    add_argument_with_former_name(group, '--out-file', '--output', '-o', dest='output_path', metavar='PATH',
                                  required=required, help="Output path")
    add_argument_with_former_name(group, '--cache-lvs', '--cache_lvs', dest='cache_lvs',
                                  type=true_or_false, default=True, help="Reuse the cache")
    add_argument_with_former_name(group, '--pre-flatten', '--pre_flatten', dest='pre_flatten',
                                  action='store_true', default=False, help="Flatten first")
    return parser


def parse(parser: argparse.ArgumentParser, *arguments: str) -> Tuple[Optional[argparse.Namespace], str]:
    """The arguments (None for a usage error) and stderr"""
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        try:
            return parser.parse_args(list(arguments)), stderr.getvalue()
        except SystemExit:
            return None, stderr.getvalue()


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Util")
class FormerOptionNameTest(unittest.TestCase):
    def test_new_names_store_their_values_without_deprecation(self):
        args, _ = parse(parser_with_former_names(), '--out-file', 'x', '--cache-lvs', 'n', '--pre-flatten')
        self.assertEqual(('x', False, True), (args.output_path, args.cache_lvs, args.pre_flatten))
        self.assertFalse(hasattr(args, 'deprecated_options'))

    def test_former_names_store_as_the_new_ones_and_are_noted(self):
        args, _ = parse(parser_with_former_names(), '--output', 'x', '--cache_lvs', 'n', '--pre_flatten')
        self.assertEqual(('x', False, True), (args.output_path, args.cache_lvs, args.pre_flatten))
        self.assertEqual([('--output', '--out-file'), ('--cache_lvs', '--cache-lvs'), ('--pre_flatten', '--pre-flatten')],
                         args.deprecated_options)

    def test_defaults_without_either_name(self):
        args, _ = parse(parser_with_former_names())
        self.assertEqual((None, True, False), (args.output_path, args.cache_lvs, args.pre_flatten))

    def test_former_names_are_hidden_from_the_help(self):
        help_text = parser_with_former_names().format_help()
        self.assertIn('--out-file', help_text)
        for former_name in ('--output', '--cache_lvs', '--pre_flatten'):
            self.assertNotIn(former_name, help_text.replace('--out-file', ''))

    def test_a_required_option_is_given_by_either_name(self):
        parser = parser_with_former_names(required=True)
        self.assertEqual('x', parse(parser, '--output', 'x')[0].output_path)
        self.assertEqual('y', parse(parser, '-o', 'y')[0].output_path)
        args, stderr = parse(parser)
        self.assertIsNone(args)
        self.assertIn('--out-file/-o is required', stderr)

    def test_both_names_are_a_usage_error(self):
        args, stderr = parse(parser_with_former_names(), '--output', 'x', '--out-file', 'y')
        self.assertIsNone(args)
        self.assertIn('not allowed with argument --output', stderr)

    def test_former_names_take_the_type_of_the_option(self):
        args, stderr = parse(parser_with_former_names(), '--cache_lvs', 'maybe')
        self.assertIsNone(args)
        self.assertIn('Boolean value expected', stderr)

    def test_warnings_name_the_new_option(self):
        args, _ = parse(parser_with_former_names(), '--output', 'x', '--pre_flatten')
        with mock.patch('klayout_pex.util.argparse_helpers.warning') as warning_mock:
            warn_deprecated_options(args)
        self.assertEqual(['--output is deprecated, use --out-file', '--pre_flatten is deprecated, use --pre-flatten'],
                         [c.args[0] for c in warning_mock.call_args_list])


@allure.parent_suite("Unit Tests")
@allure.tag("CLI", "Util")
class LogLevelArgumentTest(unittest.TestCase):
    @staticmethod
    def parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog='tool')
        add_log_level_argument(parser)
        return parser

    def test_log_level_by_name_in_any_case(self):
        self.assertEqual(LogLevel.SUBPROCESS, parse(self.parser())[0].log_level)
        self.assertEqual(LogLevel.DEBUG, parse(self.parser(), '--log-level', 'DEBUG')[0].log_level)
        self.assertEqual(LogLevel.WARNING, parse(self.parser(), '--log_level', 'warning')[0].log_level)

    def test_unknown_log_level_is_a_usage_error_naming_the_levels(self):
        args, stderr = parse(self.parser(), '--log-level', '10')
        self.assertIsNone(args)
        self.assertIn("'10' is no log level", stderr)
        self.assertIn("'debug'", stderr)
