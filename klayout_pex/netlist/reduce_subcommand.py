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
``netlist reduce``: reduce the RC parasitics of a SPICE netlist (#214), see :mod:`.netlist_reduction`
"""

from __future__ import annotations

import argparse
import os
from typing import *

import rich.console
import rich.markdown
import rich.text
from rich_argparse import RichHelpFormatter

from ..log import error, info, rule
from ..pex25d.diagnostics import ExitCode
from ..util.argparse_helpers import true_or_false
from ..util.unit_formatter import format_spice_number, parse_spice_number
from .netlist_reduction import UnknownNodesError, reduce_spice_netlist
from .rc_reduction import TIE_RESISTANCE, ReductionOptions
from .spice_rc_netlist import NetlistReadError


DEFAULTS = ReductionOptions()

EPILOG_MARKDOWN = f"""
The reduction runs on every `.SUBCKT` (and on the top level) of the netlist on its own, in this order:

1. *floating*: merge each floating island (nodes connected by resistors only among themselves, none of them kept)
   into one node
2. *TICER*: eliminate the quick nodes, whose time constant (capacitance sum / conductance sum) is at most
   `--ticer_tau`, and which have at most `--ticer_max_degree` resistors. The neighbours get the star-mesh
   transform of the node: exact at DC, and the capacitance between the nets is conserved.
   The error per node is about 2π f τ at frequency f, e.g. below 1 % up to 16 GHz with τ = 0.1 ps;
   the errors of many nodes can add up. Losses are not kept: the series resistance (the Q) of a capacitor
   shrinks or vanishes, unless τ is small against 1 / (2π f Q).
3. *floating*: eliminate the capacitor-only nodes with at most `--floating_max_degree` capacitors exactly
   (a plate between two nets becomes their series capacitance), and tie the rest to ground (node `0`)
   by {format_spice_number(TIE_RESISTANCE)}Ω, so that DC has a solution. The ties of a netlist reduced before
   (`Rtie_<n>`) are dropped first, so that it can be reduced again, e.g. with a higher degree limit

Never eliminated: the `.SUBCKT` ports, the ground nodes `0` and `gnd`, `.GLOBAL` nodes, every node of a
line that is no plain R or C (device and subcircuit terminals, sources, control statements), and the nodes
given with `--keep`. Plain R and C elements have two nodes and a number as value; all other lines are
written as they are. The reduced R and C elements are named `Rred_<n>` and `Cred_<n>`, the ties `Rtie_<n>`.

| Exit code | Meaning |
| --------- | ------- |
| 0 | success |
| 1 | the netlist can't be split into subcircuits (`.SUBCKT` and `.ENDS` do not match) |
| 2 | the command line is wrong, or a file could not be read or written |
"""


def _spice_seconds(text: str) -> float:
    """argparse type: a time constant > 0 s as a SPICE number"""
    try:
        value = parse_spice_number(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0 s, got '{text}'")
    return value


def _degree(text: str) -> int:
    """argparse type: an integer ≥ 1"""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be an integer ≥ 1, got '{text}'")
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be an integer ≥ 1, got '{text}'")
    return value


def default_output_path(input_path: str) -> str:
    """'<dir>/<name>.spice' → '<dir>/<name>_reduced.spice'"""
    base, extension = os.path.splitext(input_path)
    return f"{base}_reduced{extension}"


def add_reduce_subcommand(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "reduce",
        help="Reduce the RC parasitics of a SPICE netlist (TICER, capacitor-only nodes)",
        description="Reduce the resistors and capacitors of a SPICE netlist, e.g. the 2.5D RC output of kpex: "
                    "TICER eliminates the nodes with small time constants, "
                    "the capacitor-only nodes are eliminated exactly.",
        formatter_class=RichHelpFormatter,
        epilog=rich.console.Group(rich.text.Text('Passes, kept nodes and exit codes:', style='argparse.groups'),
                                  rich.markdown.Markdown(EPILOG_MARKDOWN, style='argparse.text')))
    parser.add_argument("input_netlist_path", metavar="INPUT_NETLIST", help="Path to the SPICE netlist to reduce")
    parser.add_argument("--output", "-o", dest="output_netlist_path", metavar="OUTPUT_NETLIST", default=None,
                        help="Path of the reduced netlist (default is INPUT_NETLIST with '_reduced' before "
                             "its extension)")
    parser.add_argument("--keep", dest="keep_nodes", metavar="NODE", action='append', default=[],
                        help="Never eliminate this node (case-insensitive, may be given more than once)")

    group_ticer = parser.add_argument_group("TICER")
    group_ticer.add_argument("--ticer", dest="ticer", type=true_or_false, default=DEFAULTS.ticer,
                             help="Eliminate the quick nodes (default is %(default)s)")
    group_ticer.add_argument("--ticer_tau", dest="ticer_tau", metavar="TAU", type=_spice_seconds,
                             default=DEFAULTS.ticer_tau,
                             help=f"Time constant threshold in s, a SPICE number like '0.1p' or '1e-13' "
                                  f"(default is {DEFAULTS.ticer_tau * 1e12:g}p)")
    group_ticer.add_argument("--ticer_max_degree", dest="ticer_max_degree", metavar="N", type=_degree,
                             default=DEFAULTS.ticer_max_degree,
                             help="Keep nodes with more resistors than this, to bound the fill-in "
                                  "(an integer ≥ 1, default is %(default)s)")

    group_floating = parser.add_argument_group("Floating nodes")
    group_floating.add_argument("--floating", dest="floating", type=true_or_false,
                                default=DEFAULTS.floating,
                                help="Merge floating islands, eliminate capacitor-only nodes "
                                     "(default is %(default)s)")
    group_floating.add_argument("--floating_max_degree", dest="floating_max_degree", metavar="N", type=_degree,
                                default=DEFAULTS.floating_max_degree,
                                help="Tie capacitor-only nodes with more capacitors than this to ground instead "
                                     "(an integer ≥ 1, default is %(default)s)")
    return parser


def run_reduce_subcommand(args: argparse.Namespace) -> ExitCode:
    """
    Validate the arguments (before reading anything), reduce, and report.

    :return: the exit code (see the epilog)
    """
    try:
        options = ReductionOptions(ticer=args.ticer,
                                   ticer_tau=args.ticer_tau,
                                   ticer_max_degree=args.ticer_max_degree,
                                   floating=args.floating,
                                   floating_max_degree=args.floating_max_degree)
    except ValueError as e:
        error(f"Invalid reduction options: {e}")
        return ExitCode.USAGE

    input_path = args.input_netlist_path
    if not os.path.isfile(input_path):
        error(f"Input netlist not found: {input_path}")
        return ExitCode.USAGE
    output_path = args.output_netlist_path or default_output_path(input_path)
    if os.path.exists(output_path) and os.path.samefile(input_path, output_path):
        error(f"The output would overwrite the input netlist: {output_path}")
        return ExitCode.USAGE

    rule('Netlist reduction')
    try:
        reduction = reduce_spice_netlist(input_path=input_path,
                                         output_path=output_path,
                                         options=options,
                                         keep=args.keep_nodes)
    except UnknownNodesError as e:
        error(str(e))
        return ExitCode.USAGE
    except NetlistReadError as e:
        error(f"Invalid netlist: {e}")
        return ExitCode.DIAGNOSTIC_ERRORS
    except OSError as e:
        error(f"Netlist reduction failed: {e}")
        return ExitCode.USAGE

    for scope in reduction.scopes:
        statistics = scope.statistics
        info(f"{scope.scope}: {scope.before} → {scope.after} "
             f"(TICER eliminated {statistics.quick_nodes} nodes; "
             f"{statistics.floating_islands} floating islands merged, {statistics.floating_island_nodes} nodes less; "
             f"{statistics.capacitor_only_nodes} capacitor-only nodes eliminated, {statistics.tied_nodes} tied)")
    info(f"Wrote reduced netlist to {reduction.output_path}")
    return ExitCode.OK
