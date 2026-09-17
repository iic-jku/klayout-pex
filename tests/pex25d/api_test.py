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
import tempfile
import unittest

import allure

# The point of this test: everything the format's consumers need comes from
# one import. Nothing below may reach into a submodule.
from klayout_pex import pex25d

from .pex25d_fixtures import MINIMAL


@allure.parent_suite('Unit Tests')
@allure.tag('PEX25D', 'API')
class Pex25DApiTest(unittest.TestCase):
    def test_every_exported_name_resolves(self):
        for name in pex25d.__all__:
            with self.subTest(name=name):
                assert hasattr(pex25d, name), f"{name} is in __all__ but not importable"

    def test_the_generated_messages_are_reachable_by_name(self):
        assert pex25d.proto.PEX25DFile().DESCRIPTOR.name == 'PEX25DFile'
        assert pex25d.proto.PEX25DScene().DESCRIPTOR.name == 'PEX25DScene'
        # a module, for the enums a consumer needs
        assert pex25d.proto.dielectric.DIELECTRIC_KIND_SIMPLE is not None
        with self.assertRaises(AttributeError):
            pex25d.proto.NoSuchMessage

    def test_every_generated_schema_is_reachable(self):
        # The namespace is discovered, not listed, so this also states that
        # nothing in it has gone stale after a protobuf re-generation.
        for name in dir(pex25d.proto):
            with self.subTest(name=name):
                assert getattr(pex25d.proto, name) is not None

    def test_the_schemas_the_format_is_made_of_are_present(self):
        # Fails when a .proto is renamed or removed — which the API and the
        # documentation have to follow. An added one needs no change here.
        required = {'diagnostics', 'dielectric', 'domain', 'file', 'geometry',
                    'meta', 'resistance', 'scene', 'source_ref', 'terminal',
                    'units', 'PEX25DFile', 'PEX25DScene'}
        assert required <= set(dir(pex25d.proto)), \
            f"missing from the PEX25D protobuf namespace: {required - set(dir(pex25d.proto))}"

    def test_the_kind_of_a_message_follows_its_descriptor(self):
        assert pex25d.kind_of(pex25d.proto.PEX25DFile()) == pex25d.ArtifactKind.FILE
        assert pex25d.kind_of(pex25d.proto.PEX25DScene()) == pex25d.ArtifactKind.SCENE
        with self.assertRaises(ValueError):
            pex25d.kind_of(pex25d.proto.units.Units())

    def test_the_pipeline_needs_no_other_import(self):
        report = pex25d.DiagnosticsReport()
        file = pex25d.read_text(MINIMAL.encode('utf-8'), report=report)
        scene = pex25d.resolve(file, report=report)

        assert pex25d.kind_of(file) == pex25d.ArtifactKind.FILE
        assert pex25d.kind_of(scene) == pex25d.ArtifactKind.SCENE
        assert pex25d.validate(file, scene=scene).exit_code == pex25d.ExitCode.OK

    def test_a_path_carries_the_kind_and_the_encoding(self):
        file = pex25d.read_text(MINIMAL.encode('utf-8'))
        scene = pex25d.resolve(file)

        with tempfile.TemporaryDirectory() as tmp_dir:
            def path(name: str) -> str:
                return os.path.join(tmp_dir, name)

            pex25d.write(file, path('tiny.pex25d'))
            pex25d.write(file, path('tiny.pex25d.pb'))
            pex25d.write(scene, path('tiny.pex25d.scene.pb'))

            assert pex25d.read(path('tiny.pex25d')) == file
            assert pex25d.read(path('tiny.pex25d.pb')) == file
            assert pex25d.read(path('tiny.pex25d.scene.pb')) == scene

    def test_a_message_the_path_does_not_describe_is_refused(self):
        # '.pex25d' is a file in text format, and the text format spells a
        # PEX25DFile only — writing a scene there has to say so.
        scene = pex25d.resolve(pex25d.read_text(MINIMAL.encode('utf-8')))
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(ValueError):
                pex25d.write(scene, os.path.join(tmp_dir, 'scene.pex25d'))

    def test_a_path_without_a_conventional_suffix_is_reported_as_such(self):
        file = pex25d.read_text(MINIMAL.encode('utf-8'))
        with self.assertRaises(pex25d.ArtifactNamingError):
            pex25d.read('cell.unknown')
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(pex25d.ArtifactNamingError):
                pex25d.write(file, os.path.join(tmp_dir, 'cell.unknown'))
