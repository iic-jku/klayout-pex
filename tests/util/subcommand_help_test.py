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

"""Sectioned subcommand help and the ``help`` subcommand of ``kpex`` and ``pex25d``."""

from __future__ import annotations

import argparse
from typing import Callable, List, Mapping, Sequence

import pytest

from klayout_pex.util.argparse_helpers import (
    SectionedHelpFormatter,
    add_help_subcommand,
    add_subcommand_sections,
    handle_help_subcommand,
)


def demo_parser(sections: Mapping[str, Sequence[str]]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='demo', description='demo: a tool',
                                     formatter_class=SectionedHelpFormatter)
    subparsers = parser.add_subparsers(dest='command', metavar='<subcommand>')
    subparsers.add_parser('show', help='Show an artifact')
    subparsers.add_parser('check', help='Check an artifact')
    add_help_subcommand(subparsers)
    add_subcommand_sections(parser, subparsers, sections)
    return parser


@pytest.mark.parametrize('sections', [
    {'Inspect': ('show',), 'Help': ('help',)},
    {'Inspect': ('show', 'check', 'gone'), 'Help': ('help',)},
    {'Inspect': ('show', 'check'), 'Again': ('show',), 'Help': ('help',)},
], ids=['missing', 'unknown', 'twice'])
def test_every_subcommand_is_in_exactly_one_section(sections: Mapping[str, Sequence[str]]):
    with pytest.raises(ValueError, match='Subcommand sections'):
        demo_parser(sections)


def test_sections_replace_the_flat_list(capsys: pytest.CaptureFixture):
    demo_parser({'Inspect': ('show', 'check'), 'Help': ('help',)}).print_help()
    lines = [line.rstrip() for line in capsys.readouterr().out.splitlines()]
    assert lines[0].endswith('<subcommand> ...')
    start = lines.index('Inspect:')
    assert lines[start:start + 6] == ['Inspect:', '  show   Show an artifact', '  check  Check an artifact',
                                      '', 'Help:', "  help   Show this help, or a subcommand's help"]
    assert not any('Positional Arguments' in line for line in lines)


def run(main: Callable[[List[str]], None], argv: List[str], capsys: pytest.CaptureFixture) -> str:
    with pytest.raises(SystemExit) as completion:
        main(argv)
    assert completion.value.code in (0, None)
    return capsys.readouterr().out


def pex25d_main(argv: List[str]):
    from klayout_pex.pex25d.pex25d_cli import Pex25DCLI
    Pex25DCLI().main(argv)


def kpex_main(argv: List[str]):
    from klayout_pex.kpex_cli import KpexCLI
    KpexCLI().main(argv)


@pytest.mark.parametrize('main, tool, subcommand, sections', [
    (pex25d_main, 'pex25d', 'export', ['Inspect:', 'Transform:', 'Exchange with other tools:',
                                       'Plugins:', 'Help:']),
    (kpex_main, 'kpex', 'extract', ['Extraction:', 'PEX25D:', 'Help:']),
], ids=['pex25d', 'kpex'])
def test_help_subcommand_is_dash_h(main: Callable[[List[str]], None], tool: str, subcommand: str,
                                   sections: List[str], capsys: pytest.CaptureFixture):
    overview = run(main, [tool, '-h'], capsys)
    assert run(main, [tool, 'help'], capsys) == overview
    assert [line for line in overview.splitlines() if line in sections] == sections
    assert run(main, [tool, 'help', subcommand], capsys) == run(main, [tool, subcommand, '-h'], capsys)


def test_unknown_help_topic_is_a_usage_error(capsys: pytest.CaptureFixture):
    parser = demo_parser({'Inspect': ('show', 'check'), 'Help': ('help',)})
    with pytest.raises(SystemExit) as completion:
        handle_help_subcommand(parser, parser.parse_args(['help', 'nosuch']))
    assert completion.value.code == 2
    assert "invalid choice: 'nosuch'" in capsys.readouterr().err
