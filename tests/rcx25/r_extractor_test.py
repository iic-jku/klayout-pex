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
from __future__ import annotations

import os
import unittest

import allure
import klayout.db as kdb

from klayout_pex.klayout.lvsdb_extractor import KLayoutExtractionContext
from klayout_pex.rcx25.r.r_extractor import RExtractionTechError, RExtractor
from klayout_pex.tech_info import TechInfo
from klayout_pex_protobuf.kpex.klayout.r_extractor_tech_pb2 import RExtractorTech


REPO_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..'))


@allure.parent_suite("Unit Tests")
@allure.tag("R", "Tech")
class RExtractorTechTest(unittest.TestCase):
    def test_lvs_layer_without_layer_in_the_tech_info_is_an_error(self):
        # NOTE: like gf180mcuD, whose tech info names the contacts differently than its LVS deck
        tech = TechInfo.parse_tech_def(jsonpb_path=os.path.join(REPO_DIR, 'klayout_pex_protobuf',
                                                                'ihp-sg13g2_tech.pb.json'))
        for layer in tech.lvs_computed_layers:
            if layer.original_layer_name == 'Cont':
                layer.layer_info.name += '_renamed'

        lvsdb = kdb.LayoutVsSchematic()
        lvsdb.read(os.path.join(REPO_DIR, 'testdata', 'klayout', 'lvs',
                                'rfnmos_w1u_l0u72_broken_rfmos_model_mapping.lvsdb.gz'))
        pex_context = KLayoutExtractionContext.prepare_extraction(top_cell='rfnmos_w1u_l0u72',
                                                                  lvsdb=lvsdb,
                                                                  tech=TechInfo(tech=tech, dielectric_filter=None),
                                                                  blackbox_devices=False)
        r_extractor = RExtractor(pex_context=pex_context,
                                 substrate_algorithm=RExtractorTech.Algorithm.ALGORITHM_TESSELATION,
                                 wire_algorithm=RExtractorTech.Algorithm.ALGORITHM_SQUARE_COUNTING,
                                 delaunay_b=0.5,
                                 delaunay_amax=0.0,
                                 via_merge_distance=0.0,
                                 skip_simplify=False)

        with self.assertRaises(RExtractionTechError) as cm:
            r_extractor.prepare_r_extractor_tech_pb(RExtractorTech())
        self.assertEqual("The tech info can't model these layers of the layout for the resistance extraction, "
                         "so their connections would be missing from the resistance network:\n"
                         "  - cont_drw (Cont): the tech info has no layer derived from it",
                         str(cm.exception))
