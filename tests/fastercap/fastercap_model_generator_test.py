#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
# Johannes Kepler University, Institute for Integrated Circuits.
#
# This file is part of KPEX 
# (see https://github.com/iic-jku/kpex).
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
import allure
import os
import pytest
import time
from typing import *
from unittest import mock

import klayout.db as kdb
from kpex.fastercap.fastercap_model_generator import FasterCapModelBuilder, FasterCapModelGenerator, HCondKey, \
    Point, Triangle


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
def test_fastercap_model_generator(tmp_path):
    ly = kdb.Layout()
    net1 = ly.create_cell("Net1")
    net2 = ly.create_cell("Net2")
    net_cells = [net1, net2]

    top = ly.create_cell("TOP")
    for cell in net_cells:
        top.insert(kdb.CellInstArray(cell.cell_index(), kdb.Trans()))

    m1 = ly.layer(1, 0)  # metal1
    v1 = ly.layer(2, 0)  # via1
    m2 = ly.layer(3, 0)  # metal3

    net1.shapes(m1).insert(kdb.Box(0, 0, 2000, 500))
    net1.shapes(v1).insert(kdb.Box(1600, 100, 1900, 400))
    net1.shapes(m2).insert(kdb.Box(1500, 0, 3000, 500))

    net2.shapes(m1).insert(kdb.Box(-1000, 0, -600, 400))
    net2.shapes(v1).insert(kdb.Box(-900, 100, -700, 300))
    net2.shapes(m2).insert(kdb.Box(-1000, 0, -600, 400))

    fcm = FasterCapModelBuilder(dbu=ly.dbu,
                                k_void=3.5,
                                delaunay_amax=0.5,
                                delaunay_b=0.5)

    fcm.add_material(name='nit', k=4.5)
    fcm.add_material(name='nit2', k=7)

    z = 0.0
    h = 0.5
    hnit = 0.1

    layer = m1
    for cell in net_cells:
        nn = cell.name
        r = kdb.Region(cell.begin_shapes_rec(layer))
        fcm.add_conductor(net_name=nn, layer=r, z=z, height=h)
        rnit = r.sized(100)
        fcm.add_dielectric(material_name='nit', layer=rnit, z=z, height=h + hnit)
        rnit2 = r.sized(200)
        fcm.add_dielectric(material_name='nit2', layer=rnit2, z=z, height=h + hnit)

    z += h

    layer = v1
    for cell in net_cells:
        nn = cell.name
        r = kdb.Region(cell.begin_shapes_rec(layer))
        fcm.add_conductor(net_name=nn, layer=r, z=z, height=h)

    z += h

    layer = m2
    for cell in net_cells:
        nn = cell.name
        r = kdb.Region(cell.begin_shapes_rec(layer))
        fcm.add_conductor(net_name=nn, layer=r, z=z, height=h)
        rnit = r.sized(100)
        fcm.add_dielectric(material_name='nit', layer=rnit, z=z, height=h + hnit)

    gen = fcm.generate()

    # self-check
    gen.check()

    output_dir_path_fc = os.path.join(tmp_path, 'FasterCap')
    output_dir_path_stl = os.path.join(tmp_path, 'STL')
    os.makedirs(output_dir_path_fc)
    os.makedirs(output_dir_path_stl)
    gen.write_fastcap(prefix='test', output_dir_path=output_dir_path_fc)
    gen.dump_stl(prefix='test', output_dir_path=output_dir_path_stl)


def touching_conductors(group_name_of_b: str) -> FasterCapModelGenerator:
    """
    :return: the conductors A and B, which touch at x = 1000: side by side, and from z = 1 µm on with a via of B on A
    """
    fcm = FasterCapModelBuilder(dbu=0.001, k_void=3.5, delaunay_amax=0.5, delaunay_b=0.5)
    fcm.add_conductor(net_name='A', layer=kdb.Region(kdb.Box(0, 0, 1000, 500)), z=0.0, height=1.0, group_name='N')
    fcm.add_conductor(net_name='B', layer=kdb.Region(kdb.Box(1000, 0, 2000, 500)), z=0.0, height=1.0,
                      group_name=group_name_of_b)
    fcm.add_conductor(net_name='B', layer=kdb.Region(kdb.Box(100, 100, 400, 400)), z=1.0, height=1.0,
                      group_name=group_name_of_b)
    return fcm.generate()


def has_triangle_at(generator: FasterCapModelGenerator, net_name: str, is_at: Callable[[Any], bool]) -> bool:
    return any(all(is_at(point) for point in triangle)
               for key, triangles in generator.cond_data.items() if key.net_name == net_name
               for triangle in triangles)


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
def test_conductors_of_a_group_have_no_surfaces_between_them():
    def is_at_the_side_of_contact(point: Any) -> bool:
        return abs(point.x - 1.0) < 1e-6

    def is_at_the_via_of_contact(point: Any) -> bool:
        return abs(point.z - 1.0) < 1e-6 and 0.1 - 1e-6 <= point.x <= 0.4 + 1e-6 and 0.1 - 1e-6 <= point.y <= 0.4 + 1e-6

    apart = touching_conductors('other')
    assert has_triangle_at(apart, 'A', is_at_the_side_of_contact)
    assert has_triangle_at(apart, 'B', is_at_the_side_of_contact)
    assert has_triangle_at(apart, 'B', is_at_the_via_of_contact)

    together = touching_conductors('N')
    assert not has_triangle_at(together, 'A', is_at_the_side_of_contact)
    assert not has_triangle_at(together, 'B', is_at_the_side_of_contact)
    assert not has_triangle_at(together, 'B', is_at_the_via_of_contact)
    assert not has_triangle_at(together, 'A', is_at_the_via_of_contact)


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
def test_geometry_check_takes_the_conductors_of_a_group_as_one_surface():
    with mock.patch('kpex.fastercap.fastercap_model_generator.error') as error_mock:
        touching_conductors('N').check()
    assert [c.args[0] for c in error_mock.call_args_list] == []


@pytest.mark.parametrize('start', [0.0, 1.0])
@pytest.mark.parametrize('middle_width', [0, 500, 1000])
def test_ending_inner_dielectric_reveals_only_first_surviving_material(start: float, middle_width: int):
    # Full, partial and absent middle coverage exercise a hidden outer film
    # becoming visible. The inner film either exists from the first plane or
    # starts inside the other two, covering both entry and exit transitions.
    builder = FasterCapModelBuilder(dbu=0.001, k_void=1, delaunay_b=0.5)
    for name, permittivity in (('inner', 4), ('middle', 7), ('outer', 2)):
        builder.add_material(name, permittivity)
    field = kdb.Region(kdb.Box(0, 0, 1000, 1000))
    builder.add_dielectric('inner', field, start, 1.0)
    if middle_width:
        builder.add_dielectric('middle', kdb.Region(kdb.Box(0, 0, middle_width, 1000)), 0, 3.0)
    builder.add_dielectric('outer', field, 0, 4.0)
    generator = builder.generate()
    top_areas = {'middle': 0.0, 'outer': 0.0}
    for key, triangles in generator.diel_data.items():
        for triangle in triangles:
            if not all(point.z == start + 1.0 for point in triangle):
                continue
            if 'inner' not in (key.inside, key.outside):
                continue
            adjacent = key.inside if key.outside == 'inner' else key.outside
            assert adjacent in top_areas
            a, b, c = triangle
            top_areas[adjacent] += abs((b.x-a.x)*(c.y-a.y) - (b.y-a.y)*(c.x-a.x))/2
    assert top_areas == pytest.approx({'middle': middle_width/1000, 'outer': 1-middle_width/1000})
    with mock.patch('kpex.fastercap.fastercap_model_generator.error') as errors:
        generator.check()
    assert not errors.call_args_list


def conductor_of_triangles(triangles: List[Triangle]) -> FasterCapModelGenerator:
    generator = FasterCapModelGenerator(dbu=0.001, k_void=1.0, delaunay_amax=0.0, delaunay_b=0.5,
                                        materials={}, net_names=['N'])
    generator.cond_data[HCondKey(net_name='N', outside=None)] = triangles
    return generator


def pillow(n: int, missing: Sequence[int] = (), end_x: Optional[float] = None) -> List[Triangle]:
    """
    :return: a flat closed surface: the triangle A B C on top, below it n triangles of a fan from C along A B,
             whose n - 1 inner points on A B are T-junctions on the edge A B of the top.
             Without the triangles of the fan at the indexes `missing`, and with the fan ending at `end_x`
    """
    length = n * 0.01
    a, b, c = Point(0.0, 0.0, 0.0), Point(length, 0.0, 0.0), Point(0.0, 1.0, 0.0)
    fan = [Point(i * 0.01, 0.0, 0.0) for i in range(n)] + [Point(length if end_x is None else end_x, 0.0, 0.0)]
    return [Triangle(a, b, c)] + [Triangle(c, fan[i + 1], fan[i]) for i in range(n) if i not in missing]


def geometry_check_errors(triangles: List[Triangle]) -> List[str]:
    with mock.patch('kpex.fastercap.fastercap_model_generator.error') as error_mock:
        conductor_of_triangles(triangles).check()
    return sorted(c.args[0] for c in error_mock.call_args_list)


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
@pytest.mark.parametrize('n', [1, 2, 3, 8])
def test_geometry_check_matches_an_edge_with_the_edges_of_triangles_along_it(n: int):
    # NOTE: 1 is the exact reverse edge, no T-junction; 2 splits from either end of the edge;
    #       from 3 on, the inner pieces are only reached by splitting the pieces again
    assert geometry_check_errors(pillow(n)) == []


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
def test_geometry_check_reports_the_piece_of_an_edge_along_a_missing_triangle():
    # NOTE: the middle triangle of the fan, whose piece of the edge A B lies between two T-junctions.
    #       The conductor's surface is reversed, its edges to C and the piece of B A remain open
    assert geometry_check_errors(pillow(3, missing=[1])) == [
        "Net 'N': edge (0, 1, 0)-(0.02, 0, 0) not connected with reverse edge (open surface)",
        "Net 'N': edge (0.01, 0, 0)-(0, 1, 0) not connected with reverse edge (open surface)",
        "Net 'N': edge (0.02, 0, 0)-(0.01, 0, 0) not connected with reverse edge (open surface)",
    ]


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
def test_geometry_check_reports_a_gap_of_one_database_unit():
    # NOTE: the fan ends one database unit before B, its last edge along A B is just shorter than that piece
    assert geometry_check_errors(pillow(2, end_x=0.019)) == [
        "Net 'N': edge (0, 1, 0)-(0.02, 0, 0) not connected with reverse edge (open surface)",
        "Net 'N': edge (0.019, 0, 0)-(0, 1, 0) not connected with reverse edge (open surface)",
        "Net 'N': edge (0.02, 0, 0)-(0.019, 0, 0) not connected with reverse edge (open surface)",
    ]


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
def test_geometry_check_accepts_a_triangle_with_an_edge_of_length_zero():
    # NOTE: two corners on the same grid point: an edge without a direction, which neither splits nor is split
    p, q = Point(1.0, 0.0, 0.0), Point(1.0001, 0.0, 0.0)
    assert geometry_check_errors(pillow(2) + [Triangle(p, q, Point(1.0, 1.0, 0.0))]) == []


@allure.parent_suite("Unit Tests")
@allure.tag("Capacitance", "FasterCap")
def test_geometry_check_resolves_many_t_junctions_on_an_edge_quickly():
    # NOTE: the check used to compare all edges again for each T-junction from either end of the edge,
    #       each with all edges at its end points, which C joins: 200 T-junctions took 48 s, now 6 ms
    triangles = pillow(200)
    start = time.perf_counter()
    assert geometry_check_errors(triangles) == []
    assert time.perf_counter() - start < 1.0
