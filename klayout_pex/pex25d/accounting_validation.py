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

"""Format-only validation of required semantics and capacitance accounting.

No geometry kernel or generated binding is imported until a caller supplies an
artifact. Mask wellformedness uses the validator's exact integer predicates.
"""

from __future__ import annotations

from typing import Any, Dict, Set

from .diagnostics import Diagnostic, DiagnosticsReport, Severity, Tier, source_ref
from .protobuf import pex25d_capacitance_accounting_pb2, pex25d_scene_pb2


def _error(report: DiagnosticsReport, code: str, message: str, source: Any = None):
    report.add(Diagnostic(code=code, severity=Severity.ERROR, tier=Tier.SEMANTIC,
                          message=message, source=source_ref(source)))


def validate_capacitance_accounting(message: Any, report: DiagnosticsReport) -> bool:
    """Check typed masks, result policies and resolved part references.

    Geometry membership/partition equivalence is verified by the resolver. This
    check is also used directly for protobuf scenes that bypass the text reader.
    Required-feature checks are separate so ingestion can reject unknown features
    without imposing complete geometric/semantic validation on a format conversion.
    """
    from .validator import Shape, Validator

    before = report.num_errors
    schema = pex25d_capacitance_accounting_pb2()
    is_scene = message.DESCRIPTOR is pex25d_scene_pb2().PEX25DScene.DESCRIPTOR
    policy = message.capacitance_accounting
    has_policy = message.HasField('capacitance_accounting')
    if has_policy and not (policy.regions or policy.exclusions or policy.excluded_substrate_nets):
        _error(report, 'PEX25D-E0281', 'Capacitance accounting policy is empty')
    layers = {layer.name for layer in message.layers} if is_scene else \
        {layer.name for layer in (*message.metals, *message.vias)}
    ground = message.ground_plane.name if message.HasField('ground_plane') else None
    region_layers: Dict[str, Set[str]] = {}
    geometry = Validator(report)
    for region in policy.regions:
        if not region.name or region.name in region_layers:
            _error(report, 'PEX25D-E0281',
                   f"Capacitance region name '{region.name}' must be nonempty and unique", region)
        mask_layers: Set[str] = set()
        region_layers[region.name] = mask_layers
        if not region.masks:
            _error(report, 'PEX25D-E0281', f"Capacitance region '{region.name}' has no layer masks", region)
        for mask in region.masks:
            if mask.layer not in layers:
                _error(report, 'PEX25D-E0282',
                       f"Capacitance region '{region.name}' mask names unknown conductor layer '{mask.layer}'", region)
            if mask.layer in mask_layers:
                _error(report, 'PEX25D-E0281',
                       f"Capacitance region '{region.name}' repeats mask layer '{mask.layer}'", region)
            mask_layers.add(mask.layer)
            if not mask.polygons:
                _error(report, 'PEX25D-E0281',
                       f"Capacitance region '{region.name}' mask on '{mask.layer}' is empty", region)
            for polygon in mask.polygons:
                geometry.check_polygon(Shape(f'accounting region {region.name}', mask.layer,
                                             False, polygon, region))

    exclusions: Set[str] = set()
    for exclusion in policy.exclusions:
        if not exclusion.name or exclusion.name in exclusions:
            _error(report, 'PEX25D-E0281',
                   f"Capacitance exclusion name '{exclusion.name}' must be nonempty and unique", exclusion)
        exclusions.add(exclusion.name)
        if exclusion.region not in region_layers:
            _error(report, 'PEX25D-E0282',
                   f"Capacitance exclusion '{exclusion.name}' names unknown region '{exclusion.region}'", exclusion)
        match exclusion.kind:
            case schema.CapacitanceExclusion.KIND_ALL_LAYER_PAIRS:
                if exclusion.layer_a or exclusion.layer_b:
                    _error(report, 'PEX25D-E0283',
                           f"ALL_LAYER_PAIRS exclusion '{exclusion.name}' must not name individual layers", exclusion)
            case schema.CapacitanceExclusion.KIND_LAYER_PAIR:
                for layer in (exclusion.layer_a, exclusion.layer_b):
                    if layer == ground:
                        continue  # the physical reference body is never locally partitioned
                    if layer not in layers or layer not in region_layers.get(exclusion.region, set()):
                        _error(report, 'PEX25D-E0282',
                               f"LAYER_PAIR exclusion '{exclusion.name}' layer '{layer}' needs a mask "
                               f"in region '{exclusion.region}' or must name the ground profile", exclusion)
            case _:
                _error(report, 'PEX25D-E0283',
                       f"Capacitance exclusion '{exclusion.name}' has unknown or unspecified kind {exclusion.kind}",
                       exclusion)

    nets = {conductor.net for conductor in message.conductors
            if conductor.net and conductor.net != 'FLOATING' and
            (not is_scene or not conductor.floating)}
    if ground:
        nets.add(message.ground_plane.net or ground)
    excluded_nets: Set[str] = set()
    for net in policy.excluded_substrate_nets:
        if net not in nets:
            _error(report, 'PEX25D-E0282', f"Substrate exclusion names unknown connected NET '{net}'")
        if net in excluded_nets:
            _error(report, 'PEX25D-E0281', f"Substrate exclusion repeats NET '{net}'")
        excluded_nets.add(net)

    if is_scene:
        part_ids: Set[str] = set()
        for conductor in message.conductors:
            for part in conductor.regions:
                nonempty = bool(part.boxes or part.polygons)
                if (part.accounting_part_id or part.accounting_regions) and not has_policy:
                    _error(report, 'PEX25D-E0284',
                           f"Conductor '{conductor.name}' has an accounting part without a policy", conductor)
                if (policy.regions and nonempty or part.accounting_regions) and not part.accounting_part_id:
                    _error(report, 'PEX25D-E0284',
                           f"Conductor '{conductor.name}' on '{part.layer}' needs a nonempty part ID", conductor)
                if part.accounting_part_id:
                    if part.accounting_part_id in part_ids:
                        _error(report, 'PEX25D-E0284', f"Duplicate accounting part ID '{part.accounting_part_id}'", conductor)
                    part_ids.add(part.accounting_part_id)
                    if not nonempty:
                        _error(report, 'PEX25D-E0284', f"Accounting part '{part.accounting_part_id}' has no geometry", conductor)
                memberships: Set[str] = set()
                for name in part.accounting_regions:
                    if name in memberships:
                        _error(report, 'PEX25D-E0284',
                               f"Accounting part '{part.accounting_part_id}' repeats region '{name}'", conductor)
                    memberships.add(name)
                    if name not in region_layers or part.layer not in region_layers[name]:
                        _error(report, 'PEX25D-E0282',
                               f"Accounting part '{part.accounting_part_id}' names region '{name}' without a mask "
                               f"on layer '{part.layer}'", conductor)
    return report.num_errors == before
