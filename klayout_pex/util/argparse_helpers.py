#! /usr/bin/env python3
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

import argparse
from enum import Enum, StrEnum
from typing import *

import rich.console
import rich.padding
import rich.table
import rich.text
from rich_argparse import RichHelpFormatter


def _group_name(name: str) -> str:
    """
    Title-case only the group names argparse invents.

    rich-argparse title-cases every group name, which mangles the acronyms this
    project uses — PEX25D would render as "Pex25D", FasterCap as "Fastercap".
    A title carrying an uppercase letter was written deliberately and is left
    alone; argparse's own all-lowercase defaults ("positional arguments",
    "options") still get capitalized.
    """
    return name if any(c.isupper() for c in name) else name.title()


RichHelpFormatter.group_name_formatter = _group_name


def render_enum_help(topic: str,
                     enum_cls: Type[Enum],
                     print_default: bool = True,
                     lowercase_strenum: bool = False) -> str:
    def canonic_string(name: str, member: str) -> str:
        if issubclass(enum_cls, StrEnum):
            if name.lower() == 'default':
                return 'default'
            return member.lower() if lowercase_strenum else member
        return name.lower()
    if not hasattr(enum_cls, 'DEFAULT'):
        print_default = False
    case_list = [f"'{canonic_string(name, member)}'"
                 for name, member in enum_cls.__members__.items()
                 if name.lower() != 'default']
    enum_help = f"{topic} ∈ \u007b{', '.join(case_list)}\u007d"
    if print_default:
        default_case: enum_cls = getattr(enum_cls, 'DEFAULT')
        if issubclass(enum_cls, StrEnum):
            default_value: str = default_case.value
            if lowercase_strenum:
                default_value = default_value.lower()
        else:
            default_value = default_case.name.lower()
        enum_help += f".\nDefaults to '{default_value}'"
    return enum_help


def true_or_false(arg) -> bool:
    if isinstance(arg, bool):
        return arg

    match str(arg).lower():
        case 'yes' | 'true' | 't' | 'y' | 1:
            return True
        case 'no' | 'false' | 'f' | 'n' | 0:
            return False
        case _:
            raise argparse.ArgumentTypeError('Boolean value expected.')


class SectionedHelpFormatter(RichHelpFormatter):
    """
    Leave the subcommands out of the option groups.

    argparse knows a single, flat subcommand list. A parser using this formatter
    shows its subcommands in sections instead, see :func:`add_subcommand_sections`.
    The usage line still names them.
    """

    def add_argument(self, action: argparse.Action):
        if not isinstance(action, argparse._SubParsersAction):
            super().add_argument(action)


def add_subcommand_sections(parser: argparse.ArgumentParser,
                            subparsers: argparse._SubParsersAction,
                            sections: Mapping[str, Sequence[str]]):
    """
    List the subcommands of ``parser`` below its description, grouped in sections.

    Call it after all subcommands are added; their help texts come from
    ``add_parser(help=...)``. The parser needs :class:`SectionedHelpFormatter`.

    :raises ValueError: unless every subcommand is in exactly one section.
    """
    help_by_name = {action.dest: action.help for action in subparsers._choices_actions}
    listed = [name for names in sections.values() for name in names]
    if sorted(listed) != sorted(help_by_name):
        raise ValueError(f"Subcommand sections list {sorted(listed)}, "
                         f"but the subcommands are {sorted(help_by_name)}")

    name_width = max(len(name) for name in listed)
    renderables: List[rich.console.RenderableType] = [
        rich.text.Text(str(parser.description), style='argparse.text')]
    for title, names in sections.items():
        grid = rich.table.Table.grid(padding=(0, 2))
        grid.add_column(min_width=name_width, no_wrap=True)
        grid.add_column()
        for name in names:
            grid.add_row(rich.text.Text(name, style='argparse.args'),
                         rich.text.Text(help_by_name[name] or '', style='argparse.help'))
        renderables += [rich.text.Text(''), rich.text.Text(f'{title}:', style='argparse.groups'),
                        rich.padding.Padding(grid, (0, 0, 0, 2))]
    parser.description = rich.console.Group(*renderables)


def add_help_subcommand(subparsers: argparse._SubParsersAction):
    """Add ``help [SUBCOMMAND]``, the same as ``-h`` on the tool or on that subcommand."""
    parser = subparsers.add_parser(
        "help",
        help="Show this help, or a subcommand's help",
        description="Show the tool's help, or with SUBCOMMAND the same as 'SUBCOMMAND -h'.",
        formatter_class=RichHelpFormatter)
    parser.add_argument("topic", nargs='?', default=None, metavar='SUBCOMMAND',
                        help="Subcommand to show the help of")


def handle_help_subcommand(parser: argparse.ArgumentParser, args: argparse.Namespace):
    """Print the help that ``help`` asked for and exit like ``-h`` does; otherwise do nothing."""
    if getattr(args, 'command', None) != 'help':
        return
    if args.topic is None:
        parser.print_help()
        parser.exit()
    parser.parse_args([args.topic, '--help'])
