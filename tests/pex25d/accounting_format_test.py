#
# --------------------------------------------------------------------------------
# SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
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

"""Accounting is mandatory semantics, not a hint that a reader may ignore.

The invalid classes exercise information loss at text/binary boundaries and
mistaken part identities. Geometric mask cases check that unsafe polygons fail
before the resolver can pass them to a native Boolean operation.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from kpex.pex25d.accounting_validation import validate_capacitance_accounting
from kpex.pex25d.capability_validation import validate_required_capabilities
from kpex.pex25d.artifact import ArtifactFormat, ArtifactKind, ArtifactSpec
from kpex.pex25d.codec import load_artifact, save_artifact
from kpex.pex25d.diagnostics import DiagnosticsReport
from kpex.pex25d.protobuf import pex25d_capacitance_accounting_pb2, pex25d_capabilities_pb2
from kpex.pex25d.reader import ReadError
from kpex.pex25d.resolver import resolve
from kpex.pex25d.validator import validate
from kpex.pex25d.writer import WriteError, write_pex25d_text
from .pex25d_fixtures import MINIMAL, codes, read


POLICY = '''\
CAP_REGION window LAYER met1 OUTER -1 -1 4 -1 4 2 -1 2
CAP_REGION window LAYER met2 OUTER -1 -1 4 -1 4 2 -1 2
CAP_EXCLUDE internal WITHIN window LAYER_PAIR met1 met2
CAP_EXCLUDE_SUBSTRATE neta
'''


def accounting_file(policy: str = POLICY) -> Any:
    return read(MINIMAL.replace('PEX25D 1.0-rc1',
                'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING') + policy)


def accounting_scene() -> Any:
    # Independent resolved representation, also covering callers that read a
    # binary scene without ever running the accounting resolver.
    scene = resolve(read(MINIMAL))
    source = accounting_file()
    scene.required_capabilities.extend(source.required_capabilities)
    scene.capacitance_accounting.CopyFrom(source.capacitance_accounting)
    for i, conductor in enumerate(scene.conductors):
        for j, part in enumerate(conductor.regions):
            part.accounting_part_id = f'part-{i}-{j}'
            if part.layer in {'met1', 'met2'}:
                part.accounting_regions.append('window')
    return scene


@pytest.mark.parametrize('make', [accounting_file, accounting_scene])
def test_accounting_valid_for_unresolved_and_resolved_artifacts(make):
    report = DiagnosticsReport()
    message = make()
    assert validate_required_capabilities(message, report)
    assert validate_capacitance_accounting(message, report), report.diagnostics


def test_geometry_only_text_remains_unchanged_in_meaning():
    original = read(MINIMAL)
    rewritten = read(write_pex25d_text(original).decode())
    assert rewritten == original
    assert not rewritten.required_capabilities
    assert not rewritten.HasField('capacitance_accounting')
    assert b'REQUIRES' not in write_pex25d_text(original)


@pytest.mark.parametrize('fmt', [ArtifactFormat.PB, ArtifactFormat.TEXTPB])
@pytest.mark.parametrize('kind,make', [(ArtifactKind.FILE, accounting_file),
                                      (ArtifactKind.SCENE, accounting_scene)])
def test_accounting_roundtrips_all_protobuf_encodings(tmp_path: Path, fmt, kind, make):
    original = make()
    spec = ArtifactSpec(str(tmp_path / 'artifact'), kind, fmt)
    save_artifact(original, spec)
    restored = load_artifact(spec)
    assert restored == original
    assert validate_capacitance_accounting(restored, DiagnosticsReport())


def test_text_roundtrip_preserves_polygon_union_holes_and_policies():
    original = accounting_file(POLICY + '''\
CAP_REGION window LAYER met1 OUTER 10 10 14 10 14 14 10 14 HOLE 11 11 12 11 12 12 11 12
CAP_EXCLUDE all WITHIN window ALL_LAYER_PAIRS
CAP_EXCLUDE reference WITHIN window LAYER_PAIR met1 subs
CAP_EXCLUDE same_layer WITHIN window LAYER_PAIR met1 met1
CAP_EXCLUDE_SUBSTRATE subs
''')
    emitted = write_pex25d_text(original)
    assert b'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING' in emitted
    assert read(emitted.decode()) == original
    mask = original.capacitance_accounting.regions[0].masks[0]
    assert len(mask.polygons) == 2
    assert len(mask.polygons[1].holes) == 1


@pytest.mark.parametrize('name', ['a # region', 'a region ' * 30, 'trailing\\'])
def test_quoted_accounting_region_names_preserved_without_comment_loss(name):
    original = accounting_file(POLICY.replace('window', f'"{name}"'))
    assert read(write_pex25d_text(original).decode()) == original


@pytest.mark.parametrize('feature', [-1, 0, 9, 11, 2 ** 31 - 1])
@pytest.mark.parametrize('make', [accounting_file, accounting_scene])
def test_unknown_required_enum_values_fail_closed_after_binary_parse(make, feature):
    message = make()
    message.required_capabilities[:] = [feature]
    restored = type(message).FromString(message.SerializeToString())
    report = validate(restored)
    assert 'PEX25D-E0280' in codes(report)


@pytest.mark.parametrize('fmt', [ArtifactFormat.PB, ArtifactFormat.TEXTPB])
@pytest.mark.parametrize('kind,make', [(ArtifactKind.FILE, accounting_file),
                                      (ArtifactKind.SCENE, accounting_scene)])
def test_codec_refuses_unknown_required_capabilities_before_returning_artifact(tmp_path: Path, fmt, kind, make):
    message = make()
    message.required_capabilities.append(11)
    spec = ArtifactSpec(str(tmp_path / 'unknown-feature'), kind, fmt)
    save_artifact(message, spec)
    report = DiagnosticsReport()
    with pytest.raises(ValueError, match='Unsupported required capability 11'):
        load_artifact(spec, report=report)
    assert 'PEX25D-E0280' in codes(report)


@pytest.mark.parametrize('header', [
    'PEX25D 1.0-rc2 REQUIRES',
    'PEX25D 1.0-rc2 REQUIRES CAPACITANCE_ACCOUNTING',
    'PEX25D 1.0-rc2 REQUIRES CAPABILITIES',
    'PEX25D 1.0-rc2 REQUIRES CAPABILITIES ,',
    'PEX25D 1.0-rc2 REQUIRES CAPABILITIES ,CAPACITANCE_ACCOUNTING',
    'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING,',
    'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING,,FUTURE',
    'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING CAPACITANCE_ACCOUNTING',
])
def test_header_requires_explicit_comma_separated_nonempty_capability_list(header):
    # Zero entries, empty endpoints and missing/extra separators are distinct
    # boundary cases. No malformed list may silently discard a requirement.
    with pytest.raises(ReadError):
        read(MINIMAL.replace('PEX25D 1.0-rc1', header))


@pytest.mark.parametrize('separator', [',', ', ', ' , ', ' ,'])
@pytest.mark.parametrize('second', ['CAPACITANCE_ACCOUNTING', 'FUTURE_ACCOUNTING'])
def test_multiple_capabilities_parse_independently_before_semantic_rejection(separator, second):
    # Only one capability is currently implemented. Both a repeated known
    # capability and an unknown next capability must be diagnosed separately,
    # regardless of whitespace around the comma.
    header = 'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING' + separator + second
    report = DiagnosticsReport()
    with pytest.raises(ReadError):
        read(MINIMAL.replace('PEX25D 1.0-rc1', header), report=report)
    messages = [diagnostic.message for diagnostic in report.diagnostics]
    expected = 'appears more than once' if second == 'CAPACITANCE_ACCOUNTING' else \
        "Unsupported required capability 'FUTURE_ACCOUNTING'"
    assert any(expected in message for message in messages), messages
    assert not any('empty entry' in message or 'comma-separated' in message for message in messages)


@pytest.mark.parametrize('header', [
    'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING',
    'PEX25D 1.0-rc2 REQUIRES CAPABILITIES   CAPACITANCE_ACCOUNTING  ',
])
def test_single_capability_is_emitted_with_explicit_clause(header):
    message = read(MINIMAL.replace('PEX25D 1.0-rc1', header))
    written = write_pex25d_text(message)
    assert b'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING\n' in written
    assert read(written.decode('utf-8')) == message


@pytest.mark.parametrize('policy', [POLICY, 'CAP_EXCLUDE_SUBSTRATE neta\n'])
def test_text_policy_without_required_header_is_never_silently_accepted(policy):
    report = DiagnosticsReport()
    with pytest.raises(ReadError):
        read(MINIMAL + policy, report=report)
    assert 'PEX25D-E0280' in codes(report)


@pytest.mark.parametrize('make', [accounting_file, accounting_scene])
def test_missing_or_duplicate_feature_is_invalid_in_protobuf_artifacts(make):
    message = make()
    feature = message.required_capabilities[0]
    message.required_capabilities.append(feature)
    assert not validate_required_capabilities(message, DiagnosticsReport())
    del message.required_capabilities[:]
    assert not validate_required_capabilities(message, DiagnosticsReport())


@pytest.mark.parametrize('kind', [-1, 0, 9, 11, 19, 21, 2 ** 31 - 1])
@pytest.mark.parametrize('make', [accounting_file, accounting_scene])
def test_unknown_or_unspecified_exclusion_kind_is_invalid(make, kind):
    message = make()
    message.capacitance_accounting.exclusions[0].kind = kind
    restored = type(message).FromString(message.SerializeToString())
    assert 'PEX25D-E0283' in codes(validate(restored))


@pytest.mark.parametrize('policy,code', [
    (POLICY + 'CAP_EXCLUDE internal WITHIN window ALL_LAYER_PAIRS\n', 'PEX25D-E0281'),
    (POLICY.replace('WITHIN window', 'WITHIN absent'), 'PEX25D-E0282'),
    (POLICY.replace('LAYER met1', 'LAYER absent'), 'PEX25D-E0282'),
    (POLICY.replace('LAYER_PAIR met1 met2', 'LAYER_PAIR via1 met2'), 'PEX25D-E0282'),
    (POLICY.replace('LAYER_PAIR met1 met2', 'LAYER_PAIR met1 air'), 'PEX25D-E0282'),
    (POLICY + 'CAP_EXCLUDE_SUBSTRATE absent\n', 'PEX25D-E0282'),
    (POLICY + 'CAP_EXCLUDE_SUBSTRATE FLOATING\n', 'PEX25D-E0282'),
    (POLICY + 'CAP_EXCLUDE_SUBSTRATE neta\n', 'PEX25D-E0281'),
])
def test_policy_references_and_duplicate_names_are_checked(policy, code):
    assert code in codes(validate(accounting_file(policy)))


@pytest.mark.parametrize('mutation', ['region_name', 'region_masks', 'mask_polygons',
                                      'duplicate_region', 'duplicate_layer', 'empty_policy'])
def test_binary_masks_require_nonempty_unique_names_and_geometry(mutation):
    message = accounting_file()
    policy = message.capacitance_accounting
    region = policy.regions[0]
    if mutation == 'region_name':
        region.name = ''
    elif mutation == 'region_masks':
        del region.masks[:]
    elif mutation == 'mask_polygons':
        del region.masks[0].polygons[:]
    elif mutation == 'duplicate_region':
        policy.regions.add().CopyFrom(region)
    elif mutation == 'duplicate_layer':
        region.masks.add().CopyFrom(region.masks[0])
    elif mutation == 'empty_policy':
        policy.Clear()
    assert 'PEX25D-E0281' in codes(validate(message))


def test_all_layer_policy_rejects_ambiguous_pair_fields():
    message = accounting_file()
    exclusion = message.capacitance_accounting.exclusions[0]
    exclusion.kind = pex25d_capacitance_accounting_pb2().CapacitanceExclusion.KIND_ALL_LAYER_PAIRS
    assert 'PEX25D-E0283' in codes(validate(message))


@pytest.mark.parametrize('count', [0, 1, 2])
def test_mask_ring_below_three_vertices_fails_before_geometric_resolution(count):
    message = accounting_file()
    ring = message.capacitance_accounting.regions[0].masks[0].polygons[0].outer
    del ring.points[count:]
    assert 'PEX25D-E0301' in codes(validate(message))


@pytest.mark.parametrize('polygon', [
    'OUTER 0 0 1 1 0 1 1 0',  # self intersection
    'OUTER 0 0 1 0 1 1 0 1 HOLE 2 2 3 2 3 3 2 3',  # outside hole
    'OUTER 0 0 1 0 2 0',  # zero area
])
def test_invalid_accounting_polygon_is_checked_without_strict_flag(polygon):
    message = accounting_file(POLICY + f'CAP_REGION bad LAYER met1 {polygon}\n')
    report = validate(message)
    assert any(d.code.startswith('PEX25D-E030') for d in report.diagnostics)


@pytest.mark.parametrize('mutation,code', [
    ('missing_id', 'PEX25D-E0284'), ('duplicate_id', 'PEX25D-E0284'),
    ('duplicate_membership', 'PEX25D-E0284'), ('unknown_membership', 'PEX25D-E0282'),
    ('wrong_layer_membership', 'PEX25D-E0282'), ('empty_part', 'PEX25D-E0284'),
    ('no_policy', 'PEX25D-E0284'), ('no_feature', 'PEX25D-E0280'),
])
def test_scene_parts_cannot_lose_or_alias_accounting_identity(mutation, code):
    scene = accounting_scene()
    first, second = scene.conductors[0].regions[:2]
    if mutation == 'missing_id':
        first.accounting_part_id = ''
    elif mutation == 'duplicate_id':
        second.accounting_part_id = first.accounting_part_id
    elif mutation == 'duplicate_membership':
        first.accounting_regions.append('window')
    elif mutation == 'unknown_membership':
        first.accounting_regions.append('absent')
    elif mutation == 'wrong_layer_membership':
        second.layer = 'via1'
        second.accounting_regions.append('window')
    elif mutation == 'empty_part':
        del first.boxes[:]
        del first.polygons[:]
    elif mutation == 'no_policy':
        scene.ClearField('capacitance_accounting')
    elif mutation == 'no_feature':
        del scene.required_capabilities[:]
    restored = type(scene).FromString(scene.SerializeToString())
    assert code in codes(validate(restored))


def test_substrate_only_policy_does_not_require_artificial_part_ids():
    scene = resolve(read(MINIMAL))
    scene.required_capabilities.append(pex25d_capabilities_pb2().REQUIRED_CAPABILITY_CAPACITANCE_ACCOUNTING)
    scene.capacitance_accounting.excluded_substrate_nets.extend(['neta', 'subs'])
    assert validate_capacitance_accounting(scene, DiagnosticsReport())


def test_writer_refuses_to_drop_unknown_or_invalid_required_semantics():
    message = accounting_file()
    message.required_capabilities.append(11)
    with pytest.raises(WriteError, match='Unsupported required capability'):
        write_pex25d_text(message)
    message.required_capabilities[:] = [10]
    message.capacitance_accounting.exclusions[0].kind = 99
    with pytest.raises(WriteError, match='unknown or unspecified kind'):
        write_pex25d_text(message)


def test_format_modules_import_without_klayout_or_generated_protobuf():
    script = '''
import importlib.abc
import sys
class Forbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'klayout', 'kpex_protobuf'}:
            raise AssertionError('eager dependency: ' + fullname)
sys.meta_path.insert(0, Forbidden())
import kpex.pex25d.accounting_validation
import kpex.pex25d.reader
import kpex.pex25d.writer
import kpex.pex25d.validator
import kpex.pex25d.codec
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                            text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr


def test_policy_records_are_order_independent_and_keep_source_positions():
    text = MINIMAL.replace('PEX25D 1.0-rc1',
                           'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING')
    records = POLICY.splitlines()
    original = read(text + '\n'.join(reversed(records)), with_source_refs=True)
    assert validate_capacitance_accounting(original, DiagnosticsReport())
    exclusion = original.capacitance_accounting.exclusions[0]
    assert exclusion.source.file == '<fixture>'
    assert exclusion.source.line == len(text.splitlines()) + 2


def test_accounting_mask_numeric_grid_boundary_is_exact():
    # Policy geometry follows the declared integer grid, including negative and
    # very large coordinates; native-kernel bounds are a separate capability.
    extent = 2 ** 63 - 1
    message = accounting_file()
    polygon = message.capacitance_accounting.regions[0].masks[0].polygons[0]
    for point, (x, y) in zip(polygon.outer.points,
                              [(-extent, -extent), (extent, -extent),
                               (extent, extent), (-extent, extent)]):
        point.x, point.y = x, y
    assert validate_capacitance_accounting(message, DiagnosticsReport())
    assert read(write_pex25d_text(message).decode()) == message


def test_empty_conductor_region_does_not_need_an_accounting_id():
    scene = accounting_scene()
    scene.conductors[0].regions.add(layer='met1')
    assert validate_capacitance_accounting(scene, DiagnosticsReport())


def test_structural_accounting_validation_and_serialization_need_no_klayout():
    script = """
import importlib.abc
import sys
class Forbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'klayout':
            raise AssertionError('geometry kernel imported: ' + fullname)
sys.meta_path.insert(0, Forbidden())
from kpex.pex25d.accounting_validation import validate_capacitance_accounting
from kpex.pex25d.diagnostics import DiagnosticsReport
from kpex.pex25d.reader import read_pex25d_text
from kpex.pex25d.writer import write_pex25d_text
original = read_pex25d_text(sys.stdin.buffer.read())
assert validate_capacitance_accounting(original, DiagnosticsReport())
assert read_pex25d_text(write_pex25d_text(original)) == original
"""
    text = MINIMAL.replace('PEX25D 1.0-rc1',
                           'PEX25D 1.0-rc2 REQUIRES CAPABILITIES CAPACITANCE_ACCOUNTING') + POLICY
    result = subprocess.run([sys.executable, '-c', script], input=text, capture_output=True,
                            text=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
