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
import math
import os
from typing import *

import rich.console
import rich.markdown
import rich.text
from rich_argparse import RichHelpFormatter

from ..log import error, info, rule
from ..pex25d.diagnostics import ExitCode
from ..util.argparse_helpers import add_argument_with_former_name, positive_spice_seconds, relative_error, true_or_false
from ..util.unit_formatter import format_spice_number, parse_spice_number
from .admittance_check import AdmittanceCheckOptions
from .netlist_reduction import UnknownNodesError, reduce_spice_netlist, reduced_netlist_path
from .rc_reduction import TIE_RESISTANCE, ReductionOptions
from .spice_rc_netlist import NetlistReadError


DEFAULTS = ReductionOptions()

EPILOG_MARKDOWN = f"""
The reduction runs on every `.SUBCKT` (and on the top level) of the netlist on its own, in this order:

1. *floating*: merge each floating island (nodes connected by resistors only among themselves, none of them kept)
   into one node
2. *TICER*: eliminate the quick nodes, whose time constant (capacitance sum / conductance sum) is at most
   `--ticer-tau`, and which have at most `--ticer-max-degree` resistors. The neighbours get the star-mesh
   transform of the node: exact at DC, and the capacitance between the nets is conserved.
   The error per node is about 2π f τ at frequency f, e.g. below 1 % up to 16 GHz with τ = 0.1 ps;
   the errors of many nodes can add up. Losses are not kept: the series resistance (the Q) of a capacitor
   shrinks or vanishes, unless τ is small against 1 / (2π f Q).
3. *floating*: eliminate the capacitor-only nodes with at most `--floating-max-degree` capacitors exactly
   (a plate between two nets becomes their series capacitance), and tie the rest to ground (node `0`)
   by {format_spice_number(TIE_RESISTANCE)}Ω, so that DC has a solution. The ties of a netlist reduced before
   (`Rtie_<n>`) are dropped first, so that it can be reduced again, e.g. with a higher degree limit

Never eliminated: the `.SUBCKT` ports, the ground nodes `0` and `gnd`, `.GLOBAL` nodes, every node of a
line that is no plain R or C (device and subcircuit terminals, sources, control statements), and the nodes
given with `--keep`. Plain R and C elements have two nodes and a number as value; all other lines are
written as they are. The reduced R and C elements are named `Rred_<n>` and `Cred_<n>`, the ties `Rtie_<n>`.

With `--check-frequency HZ` or `--check-frequency-range START STOP`, compare the written plain R/C
network with the original at every protected terminal and the global reference `0`. SPICE suffixes
are accepted, e.g. `--check-frequency-range 1Meg 10G --check-points-per-decade 10`.

- A single frequency may be zero for DC
- A range needs `0 < START ≤ STOP`, includes both endpoints, and samples logarithmically at
  `--check-points-per-decade` points per decade (default 10)
- Equal endpoints give one sample, and `--check-include-dc` adds a separate DC sample to a range
- Every sampled error must pass `--check-max-relative-error` (default 0.01, inclusive)

The error is `||Y_reduced - Y_original||_F / ||Y_original||_F`, including writer rounding and tie
resistors. Zero versus zero has error zero. A nonzero result against a zero reference has infinite
error. No absolute-error floor hides small capacitances. The report gives the worst sampled error
and its frequency. Passing covers the sampled frequencies only, without a bound on Q or between samples.

Checks accept at most 1,001 frequency points, including endpoints and DC. Each network evaluation is
bounded to 100,000 nodes/coupling entries and 1,000,000 coupling updates. A cumulative limit of
10,000,000 graph entries and coupling updates covers both networks, all scopes and every frequency.
An unevaluable sample or exceeded limit fails the check. The output remains available for inspection.

| Exit code | Meaning |
| --------- | ------- |
| 0 | success |
| 1 | the netlist can't be split into subcircuits, or the requested admittance check fails |
| 2 | the command line is wrong, or a file could not be read or written |
"""


def _degree(text: str) -> int:
    """argparse type: an integer ≥ 1"""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be an integer ≥ 1, got '{text}'")
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be an integer ≥ 1, got '{text}'")
    return value


def _frequency(text: str) -> float:
    try:
        value = parse_spice_number(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"must be a finite number of Hz ≥ 0, got '{text}'")
    return value


def add_admittance_check_arguments(parser: argparse._ActionsContainer):
    """Shared options of standalone reduction and extraction's reduction path."""
    frequencies = parser.add_mutually_exclusive_group()
    frequencies.add_argument('--check-frequency', type=_frequency, metavar='HZ', default=None,
                             help='Check full versus written reduced RC admittance at this frequency, '
                                  "a SPICE number such as '1G' (0 for DC, disabled by default)")
    frequencies.add_argument('--check-frequency-range', type=_frequency, nargs=2, metavar=('START', 'STOP'),
                             default=None, help='Check logarithmically sampled RC admittance from START to STOP Hz '
                                                '(positive inclusive bounds, SPICE suffixes accepted)')
    parser.add_argument('--check-points-per-decade', type=_degree, metavar='N', default=None,
                        help='Logarithmic sampling density for --check-frequency-range (default is 10)')
    parser.add_argument('--check-include-dc', action='store_true',
                        help='Also check DC with --check-frequency-range')
    parser.add_argument('--check-max-relative-error', type=relative_error, metavar='ERROR', default=None,
                        help='Inclusive relative Frobenius-error limit at every requested frequency '
                             '(between 0 and 1, default is 0.01)')


def admittance_check_options(args: argparse.Namespace) -> Optional[AdmittanceCheckOptions]:
    if args.check_frequency_range is None:
        if args.check_points_per_decade is not None:
            raise ValueError('--check-points-per-decade needs --check-frequency-range')
        if args.check_include_dc:
            raise ValueError('--check-include-dc needs --check-frequency-range')
        if args.check_frequency is None:
            if args.check_max_relative_error is not None:
                raise ValueError('--check-max-relative-error needs --check-frequency or --check-frequency-range')
            return None
    try:
        return AdmittanceCheckOptions(
            frequency=args.check_frequency,
            max_relative_error=0.01 if args.check_max_relative_error is None else args.check_max_relative_error,
            frequency_range=None if args.check_frequency_range is None else tuple(args.check_frequency_range),
            points_per_decade=args.check_points_per_decade,
            include_dc=args.check_include_dc)
    except ValueError as exc:
        option = '--check-frequency-range' if args.check_frequency_range is not None else '--check-frequency'
        raise ValueError(f'{option}: {exc}') from exc


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
    add_argument_with_former_name(parser, "--out-netlist", "--output", "-o", dest="output_netlist_path",
                                  metavar="OUTPUT_NETLIST", default=None,
                                  help="Path of the reduced netlist (default is INPUT_NETLIST with '_reduced' "
                                       "before its extension)")
    parser.add_argument("--keep", dest="keep_nodes", metavar="NODE", action='append', default=[],
                        help="Never eliminate this node (case-insensitive, may be given more than once)")

    group_ticer = parser.add_argument_group("TICER")
    group_ticer.add_argument("--ticer", dest="ticer", type=true_or_false, default=DEFAULTS.ticer,
                             help="Eliminate the quick nodes (default is %(default)s)")
    add_argument_with_former_name(group_ticer, "--ticer-tau", "--ticer_tau",
                                  dest="ticer_tau", metavar="TAU", type=positive_spice_seconds,
                                  default=DEFAULTS.ticer_tau,
                                  help=f"Time constant threshold in s, a SPICE number like '0.1p' or '1e-13' "
                                       f"(default is {DEFAULTS.ticer_tau * 1e12:g}p)")
    add_argument_with_former_name(group_ticer, "--ticer-max-degree", "--ticer_max_degree",
                                  dest="ticer_max_degree", metavar="N", type=_degree,
                                  default=DEFAULTS.ticer_max_degree,
                                  help="Keep nodes with more resistors than this, to bound the fill-in "
                                       "(an integer ≥ 1, default is %(default)s)")

    group_floating = parser.add_argument_group("Floating nodes")
    group_floating.add_argument("--floating", dest="floating", type=true_or_false,
                                default=DEFAULTS.floating,
                                help="Merge floating islands, eliminate capacitor-only nodes "
                                     "(default is %(default)s)")
    add_argument_with_former_name(group_floating, "--floating-max-degree", "--floating_max_degree",
                                  dest="floating_max_degree", metavar="N", type=_degree,
                                  default=DEFAULTS.floating_max_degree,
                                  help="Tie capacitor-only nodes with more capacitors than this to ground instead "
                                       "(an integer ≥ 1, default is %(default)s)")
    add_admittance_check_arguments(parser.add_argument_group('Admittance check'))
    return parser


def run_reduce_subcommand(args: argparse.Namespace) -> ExitCode:
    """
    Validate the arguments (before reading anything), reduce, and report.

    :return: the exit code (see the epilog)
    """
    try:
        reduction_options = ReductionOptions(ticer=args.ticer,
                                             ticer_tau=args.ticer_tau,
                                             ticer_max_degree=args.ticer_max_degree,
                                             floating=args.floating,
                                             floating_max_degree=args.floating_max_degree)
        check_options = admittance_check_options(args)
    except ValueError as e:
        error(f"Invalid reduction options: {e}")
        return ExitCode.USAGE

    input_path = args.input_netlist_path
    if not os.path.isfile(input_path):
        error(f"Input netlist not found: {input_path}")
        return ExitCode.USAGE
    output_path = args.output_netlist_path or reduced_netlist_path(input_path)
    if os.path.exists(output_path) and os.path.samefile(input_path, output_path):
        error(f"The output would overwrite the input netlist: {output_path}")
        return ExitCode.USAGE

    rule('Netlist reduction')
    try:
        reduction = reduce_spice_netlist(input_path=input_path,
                                         output_path=output_path,
                                         reduction_options=reduction_options,
                                         keep=args.keep_nodes,
                                         check_options=check_options)
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
        info(scope.describe())
    info(f"Wrote reduced netlist to {reduction.output_path}")
    for check in reduction.admittance_checks:
        (info if check.passed else error)(check.describe())
    if reduction.check_problems:
        return ExitCode.DIAGNOSTIC_ERRORS
    return ExitCode.OK
