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

import allure
import os
import tempfile
import unittest

from klayout_pex.pex25d.artifact import (
    ArtifactFormat, ArtifactKind, ArtifactNamingError, STDIO_PATH,
    infer_artifact_spec,
)
from klayout_pex.pex25d.codec import load_artifact, save_artifact
from klayout_pex.pex25d.resolver import resolve

from .pex25d_fixtures import MINIMAL, read


@allure.parent_suite("Unit Tests")
@allure.tag("PEX25D", "Artifact")
class Pex25DArtifactTest(unittest.TestCase):
    # ------------------------------------------------------------ inference

    def test_the_naming_convention(self):
        cases = {
            'x.pex25d': (ArtifactKind.FILE, ArtifactFormat.TEXT, False),
            'x.pex25d.pb': (ArtifactKind.FILE, ArtifactFormat.PB, False),
            'x.pex25d.textpb': (ArtifactKind.FILE, ArtifactFormat.TEXTPB, False),
            'x.pex25d.scene.pb': (ArtifactKind.SCENE, ArtifactFormat.PB, False),
            'x.pex25d.scene.textpb': (ArtifactKind.SCENE, ArtifactFormat.TEXTPB, False),
            'x.pex25d.gz': (ArtifactKind.FILE, ArtifactFormat.TEXT, True),
            'x.pex25d.scene.pb.gz': (ArtifactKind.SCENE, ArtifactFormat.PB, True),
        }
        for path, (kind, format, gzipped) in cases.items():
            with self.subTest(path=path):
                spec = infer_artifact_spec(path)
                assert (spec.kind, spec.format, spec.gzipped) == (kind, format, gzipped)

    def test_an_unconventional_name_has_to_be_stated(self):
        with self.assertRaises(ArtifactNamingError):
            infer_artifact_spec('/tmp/whatever.dat')
        spec = infer_artifact_spec('/tmp/whatever.dat',
                                   kind=ArtifactKind.SCENE,
                                   format=ArtifactFormat.PB)
        assert (spec.kind, spec.format) == (ArtifactKind.SCENE, ArtifactFormat.PB)

    def test_an_explicit_choice_beats_the_name(self):
        spec = infer_artifact_spec('x.pex25d', format=ArtifactFormat.TEXTPB)
        assert spec.format == ArtifactFormat.TEXTPB
        assert spec.kind == ArtifactKind.FILE

    def test_stdio_falls_back_to_the_defaults(self):
        spec = infer_artifact_spec(STDIO_PATH)
        assert spec.is_stdio
        assert (spec.kind, spec.format) == (ArtifactKind.FILE, ArtifactFormat.TEXT)

    def test_binary_formats_are_flagged(self):
        assert infer_artifact_spec('x.pex25d.pb').is_binary
        assert infer_artifact_spec('x.pex25d.gz').is_binary
        assert not infer_artifact_spec('x.pex25d').is_binary
        assert not infer_artifact_spec('x.pex25d.textpb').is_binary

    # ----------------------------------------------------------- round trip

    def round_trip(self, message, name: str):
        with tempfile.TemporaryDirectory() as directory:
            spec = infer_artifact_spec(os.path.join(directory, name))
            save_artifact(message, spec)
            reloaded = load_artifact(spec)
        assert reloaded.SerializeToString(deterministic=True) == \
            message.SerializeToString(deterministic=True)

    def test_a_file_survives_every_encoding(self):
        message = read(MINIMAL)
        for name in ('a.pex25d', 'a.pex25d.pb', 'a.pex25d.textpb',
                     'a.pex25d.gz', 'a.pex25d.pb.gz'):
            with self.subTest(name=name):
                self.round_trip(message, name)

    def test_a_scene_survives_the_protobuf_encodings(self):
        scene = resolve(read(MINIMAL))
        for name in ('a.pex25d.scene.pb', 'a.pex25d.scene.textpb',
                     'a.pex25d.scene.pb.gz'):
            with self.subTest(name=name):
                self.round_trip(scene, name)

    def test_a_scene_has_no_text_spelling(self):
        # Resolution is not reversible; asking for a text scene is refused when
        # the spec is built, rather than silently lowered when it is written.
        with self.assertRaises(ArtifactNamingError):
            infer_artifact_spec('a.pex25d', kind=ArtifactKind.SCENE)
        with self.assertRaises(ArtifactNamingError):
            infer_artifact_spec('a.pex25d.scene.pb', format=ArtifactFormat.TEXT)
