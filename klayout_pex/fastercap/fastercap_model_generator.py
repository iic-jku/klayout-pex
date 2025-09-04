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

# A class providing a service for building FastCap2 or FasterCap models
#
# This class is used the following way:
#
# 1) Create a FasterCapModelBuilder object
#    Specify the default k value which is the k assumed for "empty space".
#    You can also specify a maximum area and the "b" parameter for the
#    triangulation. The b parameter corresponds to the minimum angle
#    and should be <=1 (b=sin(min_angle)*2).
#    I.e. b=1 -> min_angle=30 deg, b=0.5 -> min_angle~14.5 deg.
#
# 2) Add material definitions for the dielectrics
#    Each material definition consists of a k value and
#    a material name.
#
# 3) Add layers in the 2.5d view fashion
#    Each layer is a sheet in 3d space that is extruded in vertical
#    direction with the given start and stop z (or height)
#    The layer must be a DRC::Layer or RBA::Region object.
#
#    Layers can be added in two ways:
#
#    * As conductors: specify the net name
#
#    * As dielectric layer: specify the material name
#
#    The layers can intersect. The package resolves intersections
#    based on priority: conductors first, dielectrics according to
#    their position in the "materials" definition (first entries have
#    higher prio)
#
# 4) Generate a 3d model using "generate"
#    This method returns an object you can use to generate STL files
#    or FastCap files.


from __future__ import annotations

import base64
from collections import defaultdict
import hashlib
import os
from typing import *
from dataclasses import dataclass
from functools import reduce
import math

import klayout.db as kdb

from ..log import (
    debug,
    info,
    warning,
    error,
    subproc
)


@dataclass
class FasterCapModelBuilder:
    dbu: float
    """Database unit"""

    k_void: float
    """Default dielectric of 'empty space'"""

    delaunay_amax: float
    """Maximum area parameter for the Delaunay triangulation"""

    delaunay_b: float
    """
    The delaunay_b parameter for the Delaunay triangulation 
    corresponds to the minimum angle
    and should be <=1 (b=sin(min_angle)*2).
    I.e. b=1 -> min_angle=30 deg, b=0.5 -> min_angle~14.5 deg.
    """

    def __init__(self,
                 dbu: float,
                 k_void: float,
                 delaunay_amax: float = 0.0,
                 delaunay_b: float = 1.0,
                 ):
        self.dbu = dbu
        self.k_void = k_void
        self.delaunay_amax = delaunay_amax
        self.delaunay_b = delaunay_b

        self.materials: Dict[str, float] = {}
        self.net_names: List[str] = []

        #                           layer,            zstart, zstop
        self.clayers: Dict[str, List[Tuple[kdb.Region, float, float]]] = {}
        self.dlayers: Dict[str, List[Tuple[kdb.Region, float, float]]] = {}

        info(f"DBU: {'%.12g' % self.dbu}")
        info(f"Delaunay b: {'%.12g' % self.delaunay_b}")
        info(f"Delaunay area_max: {'%.12g' % self.delaunay_amax}")

    def add_material(self, name: str, k: float):
        self.materials[name] = k

    def add_dielectric(self,
                       material_name: str,
                       layer: kdb.Region,
                       z: float,
                       height: float):
        if hasattr(layer, 'data'):
            layer = layer.data
        self._add_layer(name=material_name, layer=layer, is_dielectric=True, z=z, height=height)

    def add_conductor(self,
                      net_name: str,
                      layer: kdb.Region,
                      z: float,
                      height: float):
        if hasattr(layer, 'data'):
            layer = layer.data
        self._add_layer(name=net_name, layer=layer, is_dielectric=False, z=z, height=height)

    def _norm2z(self, z: float) -> float:
        return z * self.dbu

    def _z2norm(self, z: float) -> float:
        return math.floor(z / self.dbu + 1e-6)

    def _add_layer(self,
                   name: str,
                   layer: kdb.Region,
                   z: float,
                   height: float,
                   is_dielectric: bool):
        if is_dielectric and name not in self.materials:
            raise ValueError(f"Unknown material {name} - did you use 'add_material'?")

        zstart: float = z
        zstop: float = zstart + height

        if is_dielectric:
            if name not in self.dlayers:
                self.dlayers[name] = []
            self.dlayers[name].append((layer, self._z2norm(zstart), self._z2norm(zstop)))
        else:
            if name not in self.clayers:
                self.clayers[name] = []
            self.clayers[name].append((layer, self._z2norm(zstart), self._z2norm(zstop)))

    def generate(self) -> Optional[FasterCapModelGenerator]:
        z: List[float] = []
        for ll in (self.dlayers, self.clayers):
            for k, v in ll.items():
                for l in v:
                    z.extend((l[1], l[2]))
        z = sorted([*{*z}])  # sort & uniq
        if len(z) == 0:
            return None

        gen = FasterCapModelGenerator(dbu=self.dbu,
                                      k_void=self.k_void,
                                      delaunay_amax=self.delaunay_amax,
                                      delaunay_b=self.delaunay_b,
                                      materials=self.materials,
                                      net_names=list(self.clayers.keys()))
        for zcurr in z:
            gen.next_z(self._norm2z(zcurr))

            for nn, v in self.clayers.items():
                for l in v:
                    if l[1] <= zcurr < l[2]:
                        gen.add_in(name=f"+{nn}", layer=l[0])
                    if l[1] < zcurr <= l[2]:
                        gen.add_out(name=f"+{nn}", layer=l[0])
            for mn, v in self.dlayers.items():
                for l in v:
                    if l[1] <= zcurr < l[2]:
                        gen.add_in(name=f"-{mn}", layer=l[0])
                    if l[1] < zcurr <= l[2]:
                        gen.add_out(name=f"-{mn}", layer=l[0])

            gen.finish_z()

        gen.finalize()
        return gen


@dataclass(frozen=True)
class HDielKey:
    outside: Optional[str]
    inside: Optional[str]

    def __str__(self) -> str:
        return f"{self.outside or 'void'} <-> {self.inside or 'void'}"

    @property
    def topic(self) -> str:
        return 'dielectric'

    def reversed(self) -> HDielKey:
        return HDielKey(self.inside, self.outside)


@dataclass(frozen=True)
class HCondKey:
    net_name: str
    outside: Optional[str]

    def __str__(self) -> str:
        return f"{self.outside or 'void'} <-> {self.net_name}"

    @property
    def topic(self) -> str:
        return 'conductor'


@dataclass(frozen=True)
class VKey:
    kk: HDielKey | HCondKey
    p0: kdb.DPoint
    de: kdb.DVector


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y, self.z - other.z)

    def sq_length(self) -> float:
        return self.x**2 + self.y**2 + self.z**2

    def to_fastcap(self) -> str:
        return '%.12g %.12g %.12g' % (self.x, self.y, self.z)


def vector_product(a: Point, b: Point) -> Point:
    vp = Point(
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x
    )
    return vp


def dot_product(a: Point, b: Point) -> float:
    dp = a.x * b.x + a.y * b.y + a.z * b.z
    return dp


@dataclass(frozen=True)
class Triangle:
    p0: Point
    p1: Point
    p2: Point

    def reversed(self) -> Triangle:
        return Triangle(self.p2, self.p1, self.p0)

    def outside_reference_point(self) -> Point:
        v1 = self.p1 - self.p0
        v2 = self.p2 - self.p0
        vp = Point(v1.y  * v2.z - v1.z * v2.y,
                   -v1.x * v2.z + v1.z * v2.x,
                   v1.x  * v2.y - v1.y * v2.x)
        vp_abs = math.sqrt(vp.x ** 2 + vp.y ** 2 + vp.z ** 2)
        rp = Point(self.p0.x + vp.x / vp_abs,
                   self.p0.y + vp.y / vp_abs,
                   self.p0.z + vp.z / vp_abs)
        return rp

    def to_fastcap(self) -> str:
        return ' '.join([p.to_fastcap() for p in (self.p0, self.p1, self.p2)])

    def __len__(self):
        return 3

    def __getitem__(self, i) -> Point:
        match i:
            case 0: return self.p0
            case 1: return self.p1
            case 2: return self.p2
            case _: raise IndexError("list index out of range")


@dataclass(frozen=True)
class Edge:
    p0: Point
    p1: Point

    def vector_of_edge(self) -> Point:
        return Point(
            self.p1.x - self.p0.x,
            self.p1.y - self.p0.y,
            self.p1.z - self.p0.z
        )

    def reversed(self) -> Edge:
        return Edge(self.p1, self.p0)


@dataclass
class FasterCapModelGenerator:
    dbu: float
    """Database unit"""

    k_void: float
    """Default dielectric of 'empty space'"""

    delaunay_amax: float
    """Maximum area parameter for the Delaunay triangulation"""

    delaunay_b: float
    """
    The delaunay_b parameter for the Delaunay triangulation 
    corresponds to the minimum angle
    and should be <=1 (b=sin(min_angle)*2).
    I.e. b=1 -> min_angle=30 deg, b=0.5 -> min_angle~14.5 deg.
    """

    materials: Dict[str, float]
    """Maps material name to dielectric k"""

    net_names: List[str]

    def __init__(self,
                 dbu: float,
                 k_void: float,
                 delaunay_amax: float,
                 delaunay_b: float,
                 materials: Dict[str, float],
                 net_names: List[str]):
        self.k_void = k_void
        self.delaunay_amax = delaunay_amax
        self.delaunay_b = delaunay_b
        self.dbu = dbu
        self.materials = materials
        self.net_names = net_names

        self.z: Optional[float] = None
        self.zz: Optional[float] = None
        self.layers_in: Dict[str, kdb.Region] = {}
        self.layers_out: Dict[str, kdb.Region] = {}
        self.state: Dict[str, kdb.Region] = {}
        self.current: Dict[str, List[kdb.Region]] = {}
        self.diel_data: Dict[HDielKey, List[Triangle]] = {}
        self.diel_vdata: Dict[VKey, kdb.Region] = {}
        self.cond_data: Dict[HCondKey, List[Triangle]] = {}
        self.cond_vdata: Dict[VKey, kdb.Region] = {}

    def reset(self):
        self.layers_in = {}
        self.layers_out = {}

    def add_in(self, name: str, layer: kdb.Region):
        debug(f"add_in: {name} -> {layer}")
        if name not in self.layers_in:
            # NOTE: Calling kdb.Region([]) with the empty list enforces, that a flat layer is created.
            #       The following "+=" packs the polynomials into this flat layer and
            #       does not copy the hierarchical layer from the LayoutToNetlist database.
            self.layers_in[name] = kdb.Region([])
        self.layers_in[name] += layer

    def add_out(self, name: str, layer: kdb.Region):
        debug(f"add_out: {name} -> {layer}")
        if name not in self.layers_out:
            # NOTE: Calling kdb.Region([]) with the empty list enforces, that a flat layer is created.
            #       The following "+=" packs the polynomials into this flat layer and
            #       does not copy the hierarchical layer from the LayoutToNetlist database.
            self.layers_out[name] = kdb.Region([])
        self.layers_out[name] += layer

    def finish_z(self):
        debug(f"Finishing layer z={self.z}")

        din: Dict[str, kdb.Region] = {}
        dout: Dict[str, kdb.Region] = {}
        all_in = kdb.Region()
        all_out = kdb.Region()
        all = kdb.Region()
        all_cin: Optional[kdb.Region] = None
        all_cout: Optional[kdb.Region] = None

        for names, prefix in ((self.net_names, '+'), (self.materials.keys(), '-')):
            for nn in names:
                mk = prefix + nn

                # compute merged events
                if mk not in self.current:
                    self.current[mk] = []
                current_before = self.current[mk][0].dup() if len(self.current[mk]) >= 1 else kdb.Region()
                lin, lout, current = self._merge_events(pyra=self.current[mk],
                                                        lin=self.layers_in.get(mk, None),
                                                        lout=self.layers_out.get(mk, None))
                debug(f"Merged events & status for {mk}:")
                debug(f"  in = {lin}")
                debug(f"  out = {lout}")
                debug(f"  state = {current}")

                if mk not in self.state:
                    self.state[mk] = kdb.Region()

                # legalize in and out events
                lin_org = lin.dup()
                lout_org = lout.dup()
                lout &= self.state[mk]
                lin -= all
                lout += current & all_in
                lin += current_before & all_out
                lin -= lout_org
                lout -= lin_org

                # tracks the legalized horizontal cuts
                self.state[mk] += lin
                self.state[mk] -= lout

                din[mk] = lin
                dout[mk] = lout

                debug(f"Legalized events & status for '{mk}':")
                debug(f"  in = {din[mk]}")
                debug(f"  out = {dout[mk]}")
                debug(f"  state = {self.state[mk]}")

                all_in += lin
                all_out += lout
                all += self.state[mk]

            if prefix == '+':
                all_cin = all_in.dup()
                all_cout = all_out.dup()

        debug(f"All conductor region in: {all_cin}")
        debug(f"All conductor region out: {all_cout}")

        # check whether states are separated
        a = reduce(lambda x, y: x+y, self.state.values())
        for k, s in self.state.items():
            r: kdb.Region = s - a
            if not r.is_empty():
                error(f"State region of {k} ({s}) is not contained entirely "
                      f"in remaining all state region ({a}) - this means there is an overlap")
            a -= s

        # Now we have legalized the in and out events
        for mni in self.materials.keys():
            lin = din.get(f"-{mni}", None)
            if lin:
                lin = lin.dup()
                lin -= all_cout  # handled with the conductor
                for mno in self.materials.keys():
                    lout = dout.get(f"-{mno}", None)
                    if lout:
                        d: kdb.Region = lout & lin
                        if not d.is_empty():
                            self.generate_hdiel(below=mno, above=mni, layer=d)
                        lin -= lout
                if not lin.is_empty():
                    self.generate_hdiel(below=None, above=mni, layer=lin)

        for mno in self.materials.keys():
            lout = dout.get(f"-{mno}", None)
            if lout:
                lout = lout.dup()
                lout -= all_cin  # handled with the conductor
                for mni in self.materials.keys():
                    lin = din.get(f"-{mni}", None)
                    if lin:
                        lout -= lin
                if not lout.is_empty():
                    self.generate_hdiel(below=mno, above=None, layer=lout)

        for nn in self.net_names:
            lin = din.get(f"+{nn}", None)
            if lin:
                lin = lin.dup()
                for mno in self.materials.keys():
                    lout = dout.get(f"-{mno}", None)
                    if lout:
                        d = lout & lin
                        if not d.is_empty():
                            self.generate_hcond_in(net_name=nn, below=mno, layer=d)
                        lin -= lout
                if not lin.is_empty():
                    self.generate_hcond_in(net_name=nn, below=None, layer=lin)

        for nn in self.net_names:
            lout = dout.get(f"+{nn}", None)
            if lout:
                lout = lout.dup()
                lout -= all_cin  # handled with the conductor
                for mni in self.materials.keys():
                    lin = din.get(f"-{mni}", None)
                    if lin:
                        d = lout & lin
                        if not d.is_empty():
                            self.generate_hcond_out(net_name=nn, above=mni, layer=d)
                        lout -= lin
                if not lout.is_empty():
                    self.generate_hcond_out(net_name=nn, above=None, layer=lout)

    def next_z(self, z: float):
        debug(f"Next layer {z}")

        self.reset()

        if self.z is None:
            self.z = z
            return

        self.zz = z

        all_cond = kdb.Region()
        for nn in self.net_names:
            mk = f"+{nn}"
            if mk in self.state:
                all_cond += self.state[mk]
        all_cond = all_cond.edges()

        for i, mni in enumerate(self.materials):
            linside = self.state.get(f"-{mni}", None)
            if linside:
                linside = linside.edges()
                linside -= all_cond  # handled with the conductor
                for o, mno in enumerate(self.materials):
                    if i != o:
                        loutside = self.state.get(f"-{mno}", None)
                        if loutside:
                            loutside = loutside.edges()
                            if o > i:
                                d = loutside & linside
                                for e in d:
                                    # NOTE: we need to swap points as we started from "outside"
                                    self.generate_vdiel(outside=mno, inside=mni, edge=e.swapped_points())
                            linside -= loutside

                for e in linside:
                    self.generate_vdiel(outside=None, inside=mni, edge=e)

        for nn in self.net_names:
            mk = f"+{nn}"
            linside = self.state.get(mk, None)
            if linside:
                linside = linside.edges()
                for mno in self.materials:
                    loutside = self.state.get(f"-{mno}", None)
                    if loutside:
                        loutside = loutside.edges()
                        d = loutside & linside
                        for e in d:
                            # NOTE: we need to swap points as we started from "outside"
                            self.generate_vcond(net_name=nn, outside=mno, edge=e.swapped_points())
                        linside -= loutside
                for e in linside:
                    self.generate_vcond(net_name=nn, outside=None, edge=e)

        self.z = z

    def generate_hdiel(self,
                       below: Optional[str],
                       above: Optional[str],
                       layer: kdb.Region):
        k = HDielKey(below, above)
        debug(f"Generating horizontal dielectric surface {k} as {layer}")
        if k not in self.diel_data:
            self.diel_data[k] = []
        data = self.diel_data[k]

        for t in layer.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
            # NOTE: normal is facing downwards (to "below")
            pl = list(map(lambda pt: Point(pt.x * self.dbu, pt.y * self.dbu, self.z),
                           t.each_point_hull()))
            tri = Triangle(*pl)
            data.append(tri)
            debug(f"  {tri}")

    def generate_v_surface(self,
                           kk: HDielKey | HCondKey,
                           edge: kdb.Edge) -> Tuple[VKey, kdb.Box]:
        debug(f"Generating vertical {kk.topic} surface {kk}  with edge {edge}")

        el = math.sqrt(edge.sq_length())
        de = kdb.DVector(edge.d().x / el, edge.d().y / el)
        ne = kdb.DVector(edge.d().y / el, -edge.d().x / el)
        p0 = ne * ne.sprod(kdb.DPoint(edge.p1) - kdb.DPoint()) + kdb.DPoint()
        x1 = (edge.p1 - p0).sprod(de)
        x2 = (edge.p2 - p0).sprod(de)

        key = VKey(kk, p0, de)
        surface = kdb.Box(x1,
                          math.floor(self.z / self.dbu + 0.5),
                          x2,
                          math.floor(self.zz / self.dbu + 0.5))
        return key, surface

    def generate_vdiel(self,
                       outside: Optional[str],
                       inside: Optional[str],
                       edge: kdb.Edge):
        if edge.is_degenerate():
            return

        key, surface = self.generate_v_surface(HDielKey(outside, inside), edge)
        if key not in self.diel_vdata:
            self.diel_vdata[key] = kdb.Region()

        self.diel_vdata[key].insert(surface)

    def generate_hcond_in(self,
                          net_name: str,
                          below: Optional[str],
                          layer: kdb.Region):
        k = HCondKey(net_name, below)
        debug(f"Generating horizontal bottom conductor surface {k} as {layer}")

        if k not in self.cond_data:
            self.cond_data[k] = []
        data = self.cond_data[k]

        for t in layer.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
            # NOTE: normal is facing downwards (to "below")
            pl = list(map(lambda pt: Point(pt.x * self.dbu, pt.y * self.dbu, self.z),
                           t.each_point_hull()))
            tri = Triangle(*pl)
            data.append(tri)
            debug(f"  {tri}")

    def generate_hcond_out(self,
                           net_name: str,
                           above: Optional[str],
                           layer: kdb.Region):
        k = HCondKey(net_name, above)
        debug(f"Generating horizontal top conductor surface {k} as {layer}")

        if k not in self.cond_data:
            self.cond_data[k] = []
        data = self.cond_data[k]

        for t in layer.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
            # NOTE: normal is facing downwards (into conductor)
            pl = list(map(lambda pt: Point(pt.x * self.dbu, pt.y * self.dbu, self.z),
                           t.each_point_hull()))
            tri = Triangle(*pl)
            # now it is facing outside (to "above")
            tri = tri.reversed()
            data.append(tri)
            debug(f"  {tri}")

    def generate_vcond(self,
                       net_name: str,
                       outside: Optional[str],
                       edge: kdb.Edge):
        if edge.is_degenerate():
            return

        key, surface = self.generate_v_surface(HCondKey(net_name, outside), edge)
        if key not in self.cond_vdata:
            self.cond_vdata[key] = kdb.Region()

        self.cond_vdata[key].insert(surface)

    def triangulate(self, p0: kdb.DPoint, de: kdb.DVector, region: kdb.Region, data: List[Triangle]):
        def convert_point(pt: kdb.Point) -> Point:
            pxy = (p0 + de * pt.x) * self.dbu
            pz = pt.y * self.dbu
            return Point(pxy.x, pxy.y, pz)

        for t in region.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
            # NOTE: normal is facing outwards (to "left")
            pl = list(map(convert_point, t.each_point_hull()))
            tri = Triangle(*pl)
            # now it is facing outside (to "above")
            data.append(tri)
            debug(f"  {tri}")

    def finalize(self):
        for k, r in self.diel_vdata.items():
            debug(f"Finishing vertical dielectric plane {k.kk} at {k.p0}/{k.de}")

            if k.kk not in self.diel_data:
                self.diel_data[k.kk] = []
            data = self.diel_data[k.kk]

            self.triangulate(p0=k.p0, de=k.de, region=r, data=data)

        for k, r in self.cond_vdata.items():
            debug(f"Finishing vertical conductor plane {k.kk} at {k.p0} / {k.de}")

            if k.kk not in self.cond_data:
                self.cond_data[k.kk] = []
            data = self.cond_data[k.kk]

            self.triangulate(p0=k.p0, de=k.de, region=r, data=data)

        dk: Dict[HDielKey, List[Triangle]] = {}

        for k in self.diel_data.keys():
            kk = k.reversed()
            if kk not in dk:
                dk[k] = []
            else:
                debug(f"Combining dielectric surfaces {kk} with reverse")

        for k, v in self.diel_data.items():
            kk = k.reversed()
            if kk in dk:
                dk[kk] += list(map(lambda t: t.reversed(), v))
            else:
                dk[k] += v

        self.diel_data = dk

    def write_fastcap(self, output_dir_path: str, prefix: str) -> str:
        max_filename_length: Optional[int] = None
        try:
            max_filename_length = os.pathconf(output_dir_path, 'PC_NAME_MAX')
        except AttributeError:
            pass  # NOTE: windows does not support the os.pathconf attribute

        lst_fn = os.path.join(output_dir_path, f"{prefix}.lst")
        file_num = 0
        lst_file: List[str] = [f"* k_void={'%.12g' % self.k_void}"]

        for k, data in self.diel_data.items():
            if len(data) == 0:
                continue

            file_num += 1

            k_outside = self.materials[k.outside] if k.outside else self.k_void
            k_inside = self.materials[k.inside] if k.inside else self.k_void

            # lst_file.append(f"* Dielectric interface: outside={outside}, inside={inside}")

            fn = f"{prefix}{file_num}_outside={k.outside or '(void)'}_inside={k.inside or '(void)'}.geo"
            output_path = os.path.join(output_dir_path, fn)
            self._write_fastercap_geo(output_path=output_path,
                                      data=data,
                                      cond_name=None,
                                      cond_number=file_num,
                                      rename_conductor=False)

            # NOTE: for now, we compute the reference points for each triangle
            #       This is a FasterCap feature, reference point in the *.geo file (end of each T line)
            rp_s = "0 0 0"
            lst_file.append(f"D {fn} {'%.12g' % k_outside} {'%.12g' % k_inside} 0 0 0 {rp_s}")

        #
        # Feedback from FastFieldSolvers:
        #
        # - using the '+' trailing statements (conductor collation),
        #   only the same conductor should be collated
        #
        # - renaming different conductor numbers ('N' rule line) is not allowed (currently a bug)
        #   - Example: 1->VDD (1.geo) and 2->VDD (2.geo) is not possible
        #   - Both conductor *.geo files should have the same number
        #   - only the last conductor *.geo file should contain the 'N' rule
        #
        # - reference points
        #
        cond_data_grouped_by_net = defaultdict(list)
        for k, data in self.cond_data.items():
            if len(data) == 0:
                continue
            cond_data_grouped_by_net[k.net_name].append((k.outside, data))

        cond_num = file_num

        for nn, cond_list in cond_data_grouped_by_net.items():
            cond_num += 1
            last_cond_index = len(cond_list) - 1
            for idx, (outside, data) in enumerate(cond_list):
                file_num += 1
                k_outside = self.materials[outside] if outside else self.k_void

                outside = outside or '(void)'
                # lst_file.append(f"* Conductor interface: outside={outside}, net={nn}")
                fn = f"{prefix}{file_num}_outside={outside}_net={nn}.geo"
                if max_filename_length is not None and len(fn) > max_filename_length:
                    warning(f"Unusual long net name detected: {nn}")
                    d = hashlib.md5(nn.encode('utf-8')).digest()
                    h = base64.urlsafe_b64encode(d).decode('utf-8').rstrip('=')
                    remaining_len = len(f"{prefix}_{file_num}_outside={outside}_net=.geo")
                    short_nn = nn[0: (max_filename_length - remaining_len - len(h) - 1)] + f"_{h}"
                    fn = f"{prefix}{file_num}_outside={outside}_net={short_nn}.geo"
                output_path = os.path.join(output_dir_path, fn)
                self._write_fastercap_geo(output_path=output_path,
                                          data=data,
                                          cond_number=cond_num,
                                          cond_name=nn,
                                          rename_conductor=(idx == last_cond_index))
                collation_operator = '' if idx == last_cond_index else ' +'
                lst_file.append(f"C {fn}  {'%.12g' % k_outside}  0 0 0{collation_operator}")

        subproc(lst_fn)
        with open(lst_fn, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lst_file))
            f.write('\n')

        return lst_fn

    @staticmethod
    def _write_fastercap_geo(output_path: str,
                             data: List[Triangle],
                             cond_number: int,
                             cond_name: Optional[str],
                             rename_conductor: bool):
        subproc(output_path)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"0 GEO File\n")
            for t in data:
                f.write(f"T {cond_number}")
                f.write(' ' + t.to_fastcap())

                # compute a reference point "outside"
                rp = t.outside_reference_point()
                rp_s = rp.to_fastcap()

                f.write(f" {rp_s}\n")
            if cond_name and rename_conductor:
                f.write(f"N {cond_number} {cond_name}\n")

    def check(self):
        info("Checking …")
        errors = 0

        for mn in self.materials.keys():
            tris = self._collect_diel_tris(mn)
            info(f"Material {mn} -> {len(tris)} triangles")
            errors += self._check_tris(f"Material '{mn}'", tris)

        for nn in self.net_names:
            tris = self._collect_cond_tris(nn)
            info(f"Net '{nn}' -> {len(tris)} triangles")
            errors += self._check_tris(f"Net '{nn}'", tris)

        if errors == 0:
            info("  No errors found")
        else:
            info(f"  {errors} error{'s' if errors >= 2 else ''} found")

    def _check_tris(self, msg: str, triangles: List[Triangle]) -> int:
        errors = 0

        edge_set: Set[Edge] = set()
        edges = self._normed_edges(triangles)

        for e in edges:
            if e in edge_set:
                error(f"{msg}: duplicate edge {self._edge2s(e)}")
                errors += 1
            else:
                edge_set.add(e)

        self._split_edges(edge_set)

        for e in edge_set:
            if e.reversed() not in edge_set:
                error(f"{msg}: edge {self._edge2s(e)} not connected with reverse edge (open surface)")
                errors += 1

        return errors

    def _normed_edges(self, triangles: List[Triangle]) -> List[Edge]:
        edges = []

        def normed_dbu(p: Point):
            return Point(*tuple(map(lambda c: math.floor(c / self.dbu + 0.5),
                                    (p.x, p.y, p.z))))

        for t in triangles:
            for i in range(0, 3):
                p1 = normed_dbu(t[i])
                p2 = normed_dbu(t[(i + 1) % 3])
                edges.append(Edge(p1, p2))

        return edges

    def _point2s(self, p: Point) -> str:
        return f"(%.12g, %.12g, %.12g)" % (p.x * self.dbu, p.y * self.dbu, p.z * self.dbu)

    def _edge2s(self, e: Edge) -> str:
        return f"{self._point2s(e.p0)}-{self._point2s(e.p1)}"

    @staticmethod
    def _is_antiparallel(a: Point,
                         b: Point) -> bool:
        vp = vector_product(a, b)
        if abs(vp.sq_length()) > 0.5:  # we got normalized!
            return False

        sp = dot_product(a, b)
        return sp < 0

    def _split_edges(self, edges: set[Edge]):
        edges_by_p2: DefaultDict[Point, List[Edge]] = defaultdict(list)
        edges_by_p1: DefaultDict[Point, List[Edge]] = defaultdict(list)
        for e in edges:
            edges_by_p2[e.p1].append(e)
            edges_by_p1[e.p0].append(e)

        i = 0
        while True:
            i += 1
            subst: DefaultDict[Edge, List[Edge]] = defaultdict(list)

            for e in edges:
                ee = edges_by_p2.get(e.p0, [])
                for eee in ee:
                    ve = e.vector_of_edge()
                    veee = eee.vector_of_edge()
                    if self._is_antiparallel(ve, veee) and \
                       (veee.sq_length() < ve.sq_length() - 0.5):
                        # There is a shorter edge antiparallel ->
                        # this means we need to insert a split point into e
                        subst[e] += [Edge(e.p0, eee.p0), Edge(eee.p0, e.p1)]

            for e in edges:
                ee = edges_by_p1.get(e.p1, [])
                for eee in ee:
                    ve = e.vector_of_edge()
                    veee = eee.vector_of_edge()
                    if self._is_antiparallel(ve, veee) and \
                       (veee.sq_length() < ve.sq_length() - 0.5):
                        # There is a shorter edge antiparallel ->
                        # this means we need to insert a split point into e
                        subst[e] += [Edge(e.p0, eee.p1), Edge(eee.p1, e.p1)]

            if len(subst) == 0:
                break

            for e, replacement in subst.items():
                edges_by_p1[e.p0].remove(e)
                edges_by_p2[e.p1].remove(e)
                edges.remove(e)
                for r in replacement:
                    edges.add(r)
                    edges_by_p1[r.p0].append(r)
                    edges_by_p2[r.p1].append(r)

    def dump_stl(self, output_dir_path: str, prefix: str):
        for mn in self.materials.keys():
            tris = self._collect_diel_tris(mn)
            output_path = os.path.join(output_dir_path, f"{prefix}diel_{mn}.stl")
            self._write_as_stl(output_path, tris)

        for nn in self.net_names:
            tris = self._collect_cond_tris(nn)
            output_path = os.path.join(output_dir_path, f"{prefix}cond_{nn}.stl")
            self._write_as_stl(output_path, tris)

    @staticmethod
    def _write_as_stl(file_name: str,
                      tris: List[Triangle]):
        if len(tris) == 0:
            return

        subproc(file_name)
        with open(file_name, 'w', encoding='utf-8') as f:
            f.write("solid stl\n")
            for t in tris:
                f.write("  facet normal 0 0 0\n")
                f.write("    outer loop\n")
                t = t.reversed()
                for p in (t.p0, t.p1, t.p2):
                    f.write(f"   vertex {p.to_fastcap()}\n")
                f.write("  endloop\n")
                f.write(" endfacet\n")
            f.write("endsolid stl\n")

    @staticmethod
    def _merge_events(pyra: List[Optional[kdb.Region]],
                      lin: Optional[kdb.Region],
                      lout: Optional[kdb.Region]) -> Tuple[kdb.Region, kdb.Region, kdb.Region]:
        lin = lin.dup() if lin else kdb.Region()
        lout = lout.dup() if lout else kdb.Region()
        past = pyra[0].dup() if len(pyra) >= 1 else kdb.Region()

        for i in range(0, len(pyra)):
            ii = len(pyra) - i
            added: kdb.Region = lin & pyra[ii - 1]
            if not added.is_empty():
                if ii >= len(pyra):
                    pyra.append(kdb.Region())
                    assert len(pyra) == ii + 1
                pyra[ii] += added
                lin -= added

        if len(pyra) == 0:
            pyra.append(kdb.Region())
        pyra[0] += lin

        for i in range(0, len(pyra)):
            ii = len(pyra) - i
            removed: kdb.Region = lout & pyra[ii - 1]
            if not removed.is_empty():
                pyra[ii - 1] -= removed
                lout -= removed

        # compute merged events
        lin = pyra[0] - past
        lout = past - pyra[0]
        return lin, lout, pyra[0]

    def _collect_diel_tris(self, material_name: str) -> List[Triangle]:
        tris = []

        for k, v in self.diel_data.items():
            if material_name == k.outside:
                tris += v
            elif material_name == k.inside:
                tris += [t.reversed() for t in v]

        for k, v in self.cond_data.items():
            if material_name == k.outside:
                tris += v

        return tris

    def _collect_cond_tris(self, net_name: str) -> List[Triangle]:
        tris = []
        for k, v in self.cond_data.items():
            if k.net_name == net_name:
                tris += [t.reversed() for t in v]
        return tris
