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
Human-readable summary of a PEX25D artifact.

Not a stable output. Anything that wants to consume the contents should use
``pex25d convert --out_format textpb`` and read the protobuf text format, which
is stable by definition.
"""

from __future__ import annotations

from typing import *

from ..log import info, subproc, rule

from .artifact import ArtifactKind


ALL_SECTIONS = ['header', 'meta', 'layers', 'dielectrics',
                'conductors', 'terminals', 'resistance', 'domain']


def show(message: Any,
         kind: ArtifactKind,
         sections: Sequence[str] = ('all',)) -> None:
    selected = ALL_SECTIONS if 'all' in sections else [s for s in ALL_SECTIONS if s in sections]

    is_scene = kind == ArtifactKind.SCENE

    for section in selected:
        renderer = _RENDERERS.get(section)
        if renderer is None:
            continue
        renderer(message, is_scene)


def _grid_str(units: Any, value: int) -> str:
    """Render a grid-unit integer back into the declared LENGTH unit, for reading only."""
    try:
        return f"{value * units.grid_numerator / units.grid_denominator:g}"
    except (AttributeError, ZeroDivisionError):
        return f"{value} grid"


def _show_header(message: Any, is_scene: bool) -> None:
    rule('Header')
    suffix = f"-{message.format_version_suffix}" if message.format_version_suffix else ''
    info(f"PEX25D {message.format_version_major}.{message.format_version_minor}{suffix} "
         f"({'scene' if is_scene else 'file'})")
    if message.HasField('units'):
        u = message.units
        subproc(f"units: {u}".replace('\n', ' '))


def _show_meta(message: Any, is_scene: bool) -> None:
    metas = getattr(message, 'meta', None)
    if not metas:
        return
    rule('Metadata')
    for m in metas:
        subproc(f"{m.key} = {m.value}")


def _show_layers(message: Any, is_scene: bool) -> None:
    rule('Ground plane and layers')
    if message.HasField('ground_plane'):
        gp = message.ground_plane
        subproc(f"GROUND_PLANE {gp.name}  z {gp.zlow} … {gp.zhigh}")

    if is_scene:
        for layer in message.layers:
            extra = ''
            if layer.connects_below or layer.connects_above:
                extra = f"  connects {layer.connects_below} → {layer.connects_above}"
            subproc(f"{layer.name}  z {layer.zlow} … {layer.zhigh}{extra}")
    else:
        for metal in message.metals:
            subproc(f"METAL {metal.name}  z {metal.zlow} … {metal.zhigh}")
        for via in message.vias:
            subproc(f"VIA {via.name}  connects {via.connects_below} → {via.connects_above}")


def _show_dielectrics(message: Any, is_scene: bool) -> None:
    rule('Dielectrics')
    for d in message.dielectrics:
        depth = f"  depth {d.wrap_depth}" if is_scene else ''
        wraps = f"  wraps {d.wraps}" if d.wraps else ''
        subproc(f"{d.name}  k={d.permittivity}{wraps}{depth}")
    if message.HasField('background'):
        b = message.background
        subproc(f"{b.name}  k={b.permittivity}  (background)")


def _show_conductors(message: Any, is_scene: bool) -> None:
    rule('Conductors')
    for c in message.conductors:
        floating = '  FLOATING' if getattr(c, 'floating', False) else ''
        subproc(f"{c.name}  net {c.net}{floating}")
    if not is_scene:
        info(f"{len(message.shapes)} shape record(s)")


def _show_terminals(message: Any, is_scene: bool) -> None:
    terminals = getattr(message, 'terminals', None)
    if not terminals:
        return
    rule('Terminals')
    for t in terminals:
        subproc(f"{t.name}  layer {t.layer}")


def _show_resistance(message: Any, is_scene: bool) -> None:
    if not message.HasField('resistance_temperature'):
        return
    rule('Resistance')
    subproc(f"temperature: {message.resistance_temperature}".replace('\n', ' '))
    for r in getattr(message, 'metal_resistances', []):
        subproc(f"metal {r.metal}: {r}".replace('\n', ' '))
    for r in getattr(message, 'via_resistances', []):
        subproc(f"via {r.via}: {r}".replace('\n', ' '))


def _show_domain(message: Any, is_scene: bool) -> None:
    if is_scene:
        if not message.HasField('domain'):
            info("No computational domain (the resolver never invents one)")
            return
        rule('Computational domain')
        subproc(str(message.domain).replace('\n', ' '))
    else:
        which = message.WhichOneof('domain')
        if which is None:
            return
        rule('Computational domain')
        subproc(f"{which}: {getattr(message, which)}".replace('\n', ' '))


_RENDERERS: Dict[str, Callable[[Any, bool], None]] = {
    'header': _show_header,
    'meta': _show_meta,
    'layers': _show_layers,
    'dielectrics': _show_dielectrics,
    'conductors': _show_conductors,
    'terminals': _show_terminals,
    'resistance': _show_resistance,
    'domain': _show_domain,
}
