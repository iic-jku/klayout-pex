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

import os
from typing import *
from dataclasses import dataclass
from functools import reduce
import math

import klayout.db as kdb

from .capacitance_matrix import CapacitanceMatrixInfo, ConductorInfo
from kpex.log import (
    debug,
    info,
    warning,
    error
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
        self.diel_data: Dict[Tuple[Optional[str], Optional[str]], List[Tuple[float, float, float]]] = {}
        self.diel_vdata: Dict[Tuple[Optional[str], Optional[str], kdb.DPoint, kdb.DVector], kdb.Region] = {}
        self.cond_data: Dict[Tuple[Optional[str], Optional[str]], List[Tuple[float, float, float]]] = {}
        self.cond_vdata: Dict[Tuple[Optional[str], Optional[str], kdb.DPoint, kdb.DVector], kdb.Region] = {}

    def reset(self):
        self.layers_in = {}
        self.layers_out = {}

    def add_in(self, name: str, layer: kdb.Region):
        debug(f"add_in: {name} -> {layer}")
        if name not in self.layers_in:
            self.layers_in[name] = kdb.Region()
        self.layers_in[name] += layer

    def add_out(self, name: str, layer: kdb.Region):
        debug(f"add_out: {name} -> {layer}")
        if name not in self.layers_out:
            self.layers_out[name] = kdb.Region()
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
                                    self.generate_vdiel(left=mno, right=mni, edge=e.swapped_points())
                            linside -= loutside

                for e in linside:
                    self.generate_vdiel(left=None, right=mni, edge=e)

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
                            self.generate_vcond(net_name=nn, left=mno, edge=e.swapped_points())
                        linside -= loutside
                for e in linside:
                    self.generate_vcond(net_name=nn, left=None, edge=e)

        self.z = z

    def generate_hdiel(self,
                       below: Optional[str],
                       above: Optional[str],
                       layer: kdb.Region):
        debug(f"Generating horizontal dielectric surface "
              f"{below if below else '(void)'} <-> {above if above else '(void)'} "
              f"as {layer}")
        k = (below, above)
        if k not in self.diel_data:
            self.diel_data[k] = []
        data = self.diel_data[k]

        for t in layer.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
            # NOTE: normal is facing downwards (to "below")
            tri = list(map(lambda pt: (pt.x * self.dbu, pt.y * self.dbu, self.z),
                           t.each_point_hull()))
            data.append(tri)
            debug(f"  {tri}")

    def generate_vdiel(self,
                       left: Optional[str],
                       right: Optional[str],
                       edge: kdb.Edge):
        debug(f"Generating vertical dielectric surface "
              f"{left if left else '(void)'} <-> {right if right else '(void)'} "
              f"with edge {edge}")

        if edge.is_degenerate():
            return

        el = math.sqrt(edge.sq_length())
        de = kdb.DVector(edge.d().x / el, edge.d().y / el)
        ne = kdb.DVector(edge.d().y / el, -edge.d().x / el)
        p0 = ne * ne.sprod(kdb.DPoint(edge.p1) - kdb.DPoint()) + kdb.DPoint()
        x1 = (edge.p1 - p0).sprod(de)
        x2 = (edge.p2 - p0).sprod(de)
        k = (left, right, p0, de)
        if k not in self.diel_vdata:
            self.diel_vdata[k] = kdb.Region()

        self.diel_vdata[k].insert(kdb.Box(x1,
                                          math.floor(self.z / self.dbu + 0.5),
                                          x2,
                                          math.floor(self.zz / self.dbu + 0.5)))

    def generate_hcond_in(self,
                          net_name: str,
                          below: Optional[str],
                          layer: kdb.Region):
        debug(f"Generating horizontal bottom conductor surface "
              f"{below if below else '(void)'} <-> {net_name} as {layer}")

        k = (net_name, below)
        if k not in self.cond_data:
            self.cond_data[k] = []
        data = self.cond_data[k]

        for t in layer.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
            # NOTE: normal is facing downwards (to "below")
            tri = list(map(lambda pt: [pt.x * self.dbu, pt.y * self.dbu, self.z],
                           t.each_point_hull()))
            data.append(tri)
            debug(f"  {tri}")

    def generate_hcond_out(self,
                           net_name: str,
                           above: Optional[str],
                           layer: kdb.Region):
        debug(f"Generating horizontal top conductor surface {net_name} <-> "
              f"{above if above else '(void)'} as {layer}")

        k = (net_name, above)
        if k not in self.cond_data:
            self.cond_data[k] = []
        data = self.cond_data[k]

        for t in layer.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
            # NOTE: normal is facing downwards (into conductor)
            tri = list(map(lambda pt: [pt.x * self.dbu, pt.y * self.dbu, self.z],
                           t.each_point_hull()))
            # now it is facing outside (to "above")
            tri.reverse()
            data.append(tri)
            debug(f"  {tri}")

    def generate_vcond(self,
                       net_name: str,
                       left: Optional[str],
                       edge: kdb.Edge):
        debug(f"Generating vertical conductor surface {net_name} <-> "
              f"{left if left else '(void)'} with edge {edge}")

        if edge.is_degenerate():
            return

        el = math.sqrt(edge.sq_length())
        de = kdb.DVector(edge.d().x / el, edge.d().y / el)
        ne = kdb.DVector(edge.d().y / el, -edge.d().x / el)
        p0 = ne * ne.sprod(kdb.DPoint(edge.p1) - kdb.DPoint()) + kdb.DPoint()
        x1 = (edge.p1 - p0).sprod(de)
        x2 = (edge.p2 - p0).sprod(de)
        k = (net_name, left, p0, de)
        if k not in self.cond_vdata:
            self.cond_vdata[k] = kdb.Region()

        self.cond_vdata[k].insert(kdb.Box(x1,
                                          math.floor(self.z / self.dbu + 0.5),
                                          x2,
                                          math.floor(self.zz / self.dbu + 0.5)))

    def finalize(self):
        for k, r in self.diel_vdata.items():
            left, right, p0, de = k
            debug(f"Finishing vertical dielectric plane "
                  f"{left if left else '(void)'} <-> {right if right else '(void)'} "
                  f"at {p0}/{de}")

            kk = (left, right)
            if kk not in self.diel_data:
                self.diel_data[kk] = []
            data = self.diel_data[kk]

            def convert_point(pt) -> Tuple[float, float, float]:
                pxy = (p0 + de * pt.x) * self.dbu
                pz = pt.y * self.dbu
                return pxy.x, pxy.y, pz

            for t in r.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
                # NOTE: normal is facing outwards (to "left")
                tri = list(map(convert_point, t.each_point_hull()))
                # now it is facing outside (to "above")
                data.append(tri)
                debug(f"  {tri}")

        for k, r in self.cond_vdata.items():
            net_name, left, p0, de = k
            debug(f"Finishing vertical conductor plane "
                  f"{net_name} <-> {left if left else '(void)'} at {p0} / {de}")
            kk = (net_name, left)
            if kk not in self.cond_data:
                self.cond_data[kk] = []
            data = self.cond_data[kk]

            def convert_point(pt) -> Tuple[float, float, float]:
                pxy = (p0 + de * pt.x) * self.dbu
                pz = pt.y * self.dbu
                return pxy.x, pxy.y, pz

            for t in r.delaunay(self.delaunay_amax / self.dbu ** 2, self.delaunay_b):
                # NOTE: normal is facing outwards (to "left")
                tri = list(map(convert_point, t.each_point_hull()))
                # now it is facing outside (to "above")
                data.append(tri)
                debug(f"  {tri}")

        dk: Dict[Tuple[Optional[str], Optional[str]], List[Tuple[float, float, float]]] = {}

        for k in self.diel_data.keys():
            kk = (k[1], k[0])
            if kk not in dk:
                dk[k] = []
            else:
                debug(f"Combining dielectric surfaces "
                      f"{kk[0] if kk[0] else 'void'} <-> {kk[1] if kk[1] else 'void'} with reverse")

        for k, v in self.diel_data.items():
            kk = (k[1], k[0])
            if kk in dk:
                dk[kk] += list(map(lambda t: list(reversed(t)), v))
            else:
                dk[k] += v

        self.diel_data = dk

    def write_fastcap(self, output_dir_path: str, prefix: str) -> Tuple[str, CapacitanceMatrixInfo]:
        lst_fn = os.path.join(output_dir_path, f"{prefix}.lst")
        file_num = 0
        lst_file: List[str] = [f"* k_void={'%.12g' % self.k_void}"]

        cap_matrix_info = CapacitanceMatrixInfo([])

        for k, data in self.diel_data.items():
            if len(data) == 0:
                continue

            file_num += 1

            outside, inside = k

            k_outside = self.materials[outside] if outside else self.k_void
            k_inside = self.materials[inside] if inside else self.k_void

            outside = outside if outside else '(void)'
            inside = inside if inside else '(void)'

            lst_file.append(f"* Dielectric interface: outside={outside}, inside={inside}")

            fn = f"{prefix}_{file_num}_outside={outside}_inside={inside}.geo"
            output_path = os.path.join(output_dir_path, fn)
            self._write_fastercap_geo(file_number=file_num,
                                      output_path=output_path,
                                      data=data,
                                      cond_name=None)

            # compute one reference point "outside"
            t0 = data[0]
            v1: List[float] = list(map(lambda i: t0[1][i] - t0[0][i], (0, 1, 2)))
            v2: List[float] = list(map(lambda i: t0[2][i] - t0[0][i], (0, 1, 2)))
            vp = [v1[1] * v2[2] - v1[2] * v2[1],
                  -v1[0] * v2[2] + v1[2] * v2[0],
                  v1[0] * v2[1] - v1[1] * v2[0]]
            vp_abs = math.sqrt(vp[0] ** 2 + vp[1] ** 2 + vp[2] ** 2)
            rp: List[float] = list(map(lambda i: t0[0][i] + vp[i] / vp_abs, (0, 1, 2)))
            rp_s = ' '.join(map(lambda c: f"{'%.12g' % c}", rp))
            lst_file.append(f"D {fn} {'%.12g' % k_outside} {'%.12g' % k_inside} 0 0 0 {rp_s}")

        for k, data in self.cond_data.items():
            if len(data) == 0:
                continue

            file_num += 1
            nn, outside = k
            k_outside = self.materials[outside] if outside else self.k_void

            cap_matrix_info.conductors.append(
                ConductorInfo(fastcap_index=file_num, net=nn, outside_dielectric=outside)
            )

            outside = outside if outside else '(void)'
            lst_file.append(f"* Conductor interface: outside={outside}, net={nn}")
            fn = f"{prefix}_{file_num}_outside={outside}_net={nn}.geo"
            output_path = os.path.join(output_dir_path, fn)
            self._write_fastercap_geo(file_number=file_num,
                                      output_path=output_path,
                                      data=data,
                                      cond_name=nn)

            lst_file.append(f"C {fn}  {'%.12g' % k_outside}  0 0 0  +")

        info(f"Writing FasterCap list file: {lst_fn}")
        with open(lst_fn, "w") as f:
            f.write('\n'.join(lst_file))
            f.write('\n')

        return lst_fn, cap_matrix_info

    @staticmethod
    def _write_fastercap_geo(file_number: int,
                             output_path: str,
                             data: List[Tuple[float, float, float]],
                             cond_name: Optional[str]):
        info(f"Writing FasterCap geo file: {output_path}")
        with open(output_path, "w") as f:
            title = f"0 file #{file_number}"
            if cond_name:
                title += f" (net {cond_name}"
            title += '\n'
            f.write(title)
            for t in data:
                f.write(f"T {file_number}")
                for p in t:
                    f.write(' ' + ' '.join(map(lambda c: '%.12g' % c, p)))
                f.write('\n')
            if cond_name:
                f.write(f"N {file_number} {cond_name}")

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

    def _check_tris(self, msg: str, triangles: List[Tuple[float, float, float]]) -> int:
        errors = 0

        edge_set: set[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = set()
        edges = self._normed_edges(triangles)

        for e in edges:
            if e in edge_set:
                error(f"{msg}: duplicate edge {self._edge2s(e)}")
                errors += 1
            else:
                edge_set.add(e)

        self._split_edges(edge_set)

        for e in edge_set:
            if reversed(e) in edge_set:
                error(f"{msg}: edge {self._edge2s(e)} not connected with reverse edge (open surface)")
                errors += 1

        return errors

    def _normed_edges(self, triangles: List[Tuple[float, float, float]]) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
        edges = []

        for t in triangles:
            for i in range(0, 3):
                p1 = t[i]
                p2 = t[(i + 1) % 3]
                p1 = tuple(map(lambda c: math.floor(c / self.dbu + 0.5), p1))
                p2 = tuple(map(lambda c: math.floor(c / self.dbu + 0.5), p2))
                edges.append((p1, p2))

        return edges

    @staticmethod
    def _vector_of_edge(e: Tuple[Tuple[float, float, float], Tuple[float, float, float]]) -> Tuple[float, float, float]:
        return (
            e[1][0] - e[0][0],
            e[1][1] - e[0][2],
            e[1][2] - e[0][2]
        )

    def _point2s(self, p: Tuple[float, float, float]) -> str:
        return f"(%.12g, %.12g, %.12g)" % (p[0] * self.dbu, p[1] * self.dbu, p[2] * self.dbu)

    def _edge2s(self, e: Tuple[Tuple[float, float, float], Tuple[float, float, float]]) -> str:
        return f"{self._point2s(e[0])}-{self._point2s(e[1])}"

    def _is_antiparallel(self,
                         a: Tuple[float, float, float],
                         b: Tuple[float, float, float]) -> bool:
        # cross product
        vp: Tuple[float, float, float] = (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

        if abs(self._sq_length(vp)) > 0.5:  # we got normalized!
            return False

        # dot product
        sp = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
        return sp < 0

    @staticmethod
    def _sq_length(edge: Tuple[float, float, float]) -> float:
        return edge[0]**2 + edge[1]**2 + edge[2]**2

    def _split_edges(self, edges: set[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]):
        edges_by_p2: Dict = {}
        edges_by_p1: Dict = {}
        for e in edges:
            if e[1] not in edges_by_p2:
                edges_by_p2[e[1]] = []
            edges_by_p2[e[1]].append(e)
            if e[0] not in edges_by_p1:
                edges_by_p1[e[0]] = []
            edges_by_p1[e[0]].append(e)

        while True:
            subst: Dict = {}

            for e in edges:
                ee = edges_by_p2.get(e[0], [])
                for eee in ee:
                    ve = self._vector_of_edge(e)
                    veee = self._vector_of_edge(eee)
                    if self._is_antiparallel(ve, veee) and \
                       self._sq_length(veee) < self._sq_length(ve) - 0.5:
                        # There is a shorter edge antiparallel ->
                        # this means we need to insert a split point into e
                        if e not in subst:
                            subst[e] = []
                        subst[e].append(((e[0], ee[0]), (ee[0], e[1])))

            for e in edges:
                ee = edges_by_p1.get(e[1], [])
                for eee in ee:
                    ve = self._vector_of_edge(e)
                    veee = self._vector_of_edge(eee)
                    if self._is_antiparallel(ve, veee) and \
                       self._sq_length(veee) < self._sq_length(ve) - 0.5:
                        # There is a shorter edge antiparallel ->
                        # this means we need to insert a split point into e
                        if e not in subst:
                            subst[e] = []
                        subst[e].append(((e[0], ee[1]), (ee[1], e[1])))

            if len(subst) == 0:
                break

            for e, replacement in subst.items():
                edges_by_p1[e[0]].remove(e)
                edges_by_p2[e[1]].remove(e)
                edges.remove(e)
                for r in replacement:
                    edges.add(r)
                    if r[0] not in edges_by_p1:
                        edges_by_p1[r[0]] = []
                    edges_by_p1[r[0]].append(r)
                    if r[1] not in edges_by_p2:
                        edges_by_p2[r[1]] = []
                    edges_by_p2[r[1]].append(r)

    def dump_stl(self, output_dir_path: str):
        for mn in self.materials.keys():
            tris = self._collect_diel_tris(mn)
            output_path = os.path.join(output_dir_path, f"diel_{mn}.stl")
            self._write_as_stl(output_path, tris)

        for nn in self.net_names:
            tris = self._collect_cond_tris(nn)
            output_path = os.path.join(output_dir_path, f"cond_{nn}.stl")
            self._write_as_stl(output_path, tris)

    @staticmethod
    def _write_as_stl(file_name: str,
                      tris: List[Tuple[float, float, float]]):
        if len(tris) == 0:
            return

        info(f"Writing STL file {file_name}")
        with open(file_name, "w") as f:
            f.write("solid stl\n")
            for t in tris:
                f.write("  facet normal 0 0 0\n")
                f.write("    outer loop\n")
                t = list(t)
                t.reverse()
                for p in t:
                    f.write("   vertex %.12g %.12g %.12g\n" % tuple(p))
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

    def _collect_diel_tris(self, material_name: str) -> List[Tuple[float, float, float]]:
        tris = []

        for k, v in self.diel_data.items():
            outside, inside = k
            if material_name == outside:
                tris += v
            elif material_name == inside:
                tris += list(map(lambda t: list(reversed(t)), v))

        for k, v in self.cond_data.items():
            nn, outside = k
            if material_name == outside:
                tris += v

        return tris

    def _collect_cond_tris(self, net_name: str) -> List[Tuple[float, float, float]]:
        tris = []
        for k, v in self.cond_data.items():
            nn, outside = k
            if nn == net_name:
                tris += list(map(lambda t: list(reversed(t)), v))
        return tris
