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

"""Standalone, explicitly selected grounding of SPICE parasitic capacitance."""

import argparse
from dataclasses import replace

import rich.console
import rich.markdown
import rich.text
from rich_argparse import RichHelpFormatter

from .coupling import CouplingPolicyError
from .netlist_grounding import GroundingOptions, ground_spice_netlist, grounded_netlist_path, read_net_map
from .spice_rc_netlist import NetlistReadError
from ..log import error, info, warning
from ..pex25d.diagnostics import ExitCode


EPILOG = """
Select extracted elements explicitly. Defaults select `Cext_*`, `Cgrnd_*` and `Rext_*`.
`--capacitor` and `--resistor` replace their respective defaults and may be repeated.
Patterns and SPICE node names are case-insensitive. Quote patterns to prevent shell expansion.
Selected elements must have exactly two nodes and a finite numeric value. Unselected devices,
resistors, comments, directives and other scopes remain verbatim.

Selected resistors define distributed conductors without being shorted or rewritten. Subcircuit
ports, global nodes, terminals on unselected device/source lines and `--keep` nodes retain their
conductors. All other conductors are floating. A flat `--net-map` JSON object such as
`{"A1": "A", "A2": "A"}` can identify disconnected pieces of the same conductor.
It cannot assign different conductors to nodes connected by selected resistors.

Capacitor-only floating nodes are eliminated exactly before grounding. Floating resistive islands
and elimination exceeding the shared 64-neighbor limit fail without writing output.
Each remaining inter-net capacitor becomes its full value to `--reference` at both ends.
Capacitance within a conductor, including distributed reference nodes, stays at its original ends.
The reference is explicit and must already be a node or port in the selected scope, or `0`/`gnd`.

This intentionally removes inter-net transfer/crosstalk. It preserves diagonal capacitance after
floating elimination, not arbitrary distributed-RC port impedance or switching-dependent Miller effects.
Use a coupled netlist with intentional capacitors represented as retained devices. Capacitance from
a white-boxed device cannot be distinguished from parasitics after extraction.

| Exit code | Meaning |
| --------- | ------- |
| 0 | grounded netlist written |
| 1 | invalid selected elements, malformed netlist, or unsupported floating network |
| 2 | invalid options, ambiguous scope, unknown nodes, or file I/O failure |
"""


def add_ground_subcommand(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        'ground', help='Ground selected parasitic coupling after exact floating-capacitance elimination',
        description='Ground inter-net capacitance in a SPICE netlist without layout or technology data.',
        formatter_class=RichHelpFormatter,
        epilog=rich.console.Group(rich.text.Text('Selection, approximation and exit codes:', style='argparse.groups'),
                                  rich.markdown.Markdown(EPILOG, style='argparse.text')))
    parser.add_argument('input_netlist_path', metavar='INPUT_NETLIST')
    parser.add_argument('--out-netlist', '-o', dest='output_netlist_path', metavar='OUTPUT_NETLIST',
                        help="Output netlist (default: INPUT_NETLIST with '_grounded' before its extension)")
    parser.add_argument('--reference', required=True, metavar='NODE', help='Reference for new grounded loads')
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--cell', dest='cell_name', metavar='NAME', help='Subcircuit to transform')
    scope.add_argument('--top-level', action='store_true', help='Transform only elements outside subcircuits')
    parser.add_argument('--capacitor', action='append', metavar='PATTERN',
                        help='Parasitic capacitor name pattern (default: Cext_* and Cgrnd_*)')
    parser.add_argument('--resistor', action='append', metavar='PATTERN',
                        help='Parasitic resistor name pattern (default: Rext_*)')
    parser.add_argument('--keep', action='append', default=[], metavar='NODE',
                        help='Retain this node and its conductor (repeatable)')
    parser.add_argument('--net-map', metavar='JSON', help='Flat node-to-conductor map extending inferred identities')
    return parser


def run_ground_subcommand(args: argparse.Namespace) -> ExitCode:
    try:
        options = GroundingOptions(
            reference=args.reference,
            capacitor_patterns=tuple(args.capacitor) if args.capacitor is not None else ('Cext_*', 'Cgrnd_*'),
            resistor_patterns=tuple(args.resistor) if args.resistor is not None else ('Rext_*',),
            keep_nodes=tuple(args.keep), cell_name=args.cell_name, top_level=args.top_level)
        if args.net_map is not None:
            options = replace(options, net_by_node=read_net_map(args.net_map))
        result = ground_spice_netlist(args.input_netlist_path,
                                      args.output_netlist_path or grounded_netlist_path(args.input_netlist_path),
                                      options)
    except (CouplingPolicyError, NetlistReadError) as exc:
        error(str(exc))
        error('Keep the coupled input for unsupported networks, or adjust explicit parasitic selection')
        return ExitCode.DIAGNOSTIC_ERRORS
    except (ValueError, OSError) as exc:
        error(str(exc))
        return ExitCode.USAGE
    info(f'{result.scope}: {result.capacitors_read} selected capacitors -> {result.capacitors_written} grounded capacitors')
    if result.floating_nodes:
        warning('Eliminated floating nodes: ' + ', '.join(result.floating_nodes)
                + '. Verify these conductors have no external connection')
    warning('Grounding removes inter-net transfer admittance and preserves reduced nodal capacitance, '
            'not arbitrary distributed-RC port impedance')
    info(f'Wrote grounded netlist to {result.output_path}')
    return ExitCode.OK
