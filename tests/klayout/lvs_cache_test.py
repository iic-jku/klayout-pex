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
import argparse
import filecmp
import io
import os
import shutil
import tempfile
import unittest
from typing import *
from unittest import mock

from packaging.version import Version

from klayout_pex.kpex_cli import InputMode, KpexCLI
from klayout_pex.klayout.lvs_cache import (
    FINGERPRINT_FORMAT_VERSION,
    LVSCacheEntry,
    LVSInputFingerprint,
    deck_fingerprint,
    fingerprint_differences,
    lvs_input_fingerprint,
    read_fingerprint,
    write_fingerprint,
)
from klayout_pex.tool_version_constraints import Tool


TESTDATA_DIR = os.path.realpath(os.path.join(__file__, '..', '..', '..', 'testdata'))

# any LVS database will do, as long as it can be told apart from the one a (fake) LVS run writes
CACHED_LVSDB_PATH = os.path.join(TESTDATA_DIR, 'klayout', 'lvs',
                                 'rfnmos_w1u_l0u72_broken_rfmos_model_mapping.lvsdb.gz')
CELL_NAME = 'rfnmos_w1u_l0u72'


def write_file(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


class FakeKLayoutLVS:
    """
    Stands in for subprocess.Popen, emulating a successful KLayout LVS run
    """
    def __init__(self):
        self.call_count = 0

    def __call__(self, args: List[str], **kwargs):
        self.call_count += 1
        report_path = next(a.removeprefix('report=') for a in args if a.startswith('report='))
        write_file(report_path, '#%lvsdb-klayout\n')
        proc = mock.Mock()
        proc.stdout = io.StringIO("")
        proc.returncode = 0
        return proc


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="lvs_cache_")
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def make_deck(self, dir_name: str = 'deck') -> str:
        deck_dir_path = os.path.join(self.tmp_dir, dir_name)
        write_file(os.path.join(deck_dir_path, 'sg13g2.lvs'), '# %include rule_decks/globals.lvs\n')
        write_file(os.path.join(deck_dir_path, 'rule_decks', 'globals.lvs'), 'RF_TO_BASE_MOS_MODEL = {}\n')
        return os.path.join(deck_dir_path, 'sg13g2.lvs')

    def fingerprint(self, **overrides) -> LVSInputFingerprint:
        kwargs = dict(pdk='ihp-sg13g2',
                      klayout_version='0.30.12',
                      lvs_script_path=os.path.join(self.tmp_dir, 'deck', 'sg13g2.lvs'),
                      script_parameters={'run_mode': 'deep', 'no_simplify': 'true'},
                      gds_path=os.path.join(self.tmp_dir, 'cell.gds'),
                      cell_name='cell',
                      schematic_path=os.path.join(self.tmp_dir, 'cell.spice'))
        kwargs.update(overrides)
        return lvs_input_fingerprint(**kwargs)


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "KLayout")
class LVSInputFingerprintTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.lvs_script_path = self.make_deck()
        write_file(os.path.join(self.tmp_dir, 'cell.gds'), 'layout')
        write_file(os.path.join(self.tmp_dir, 'cell.spice'), '.subckt cell VDD VSS\n.ends\n')

    def test_deck_covers_every_file_by_relative_path(self):
        fingerprint = deck_fingerprint(self.lvs_script_path)
        self.assertEqual(self.lvs_script_path, fingerprint.script_path)
        self.assertEqual(['rule_decks/globals.lvs', 'sg13g2.lvs'],
                         sorted(fingerprint.sha256_by_relative_path.keys()))

    def test_deck_skips_hidden_files(self):
        deck_dir_path = os.path.dirname(self.lvs_script_path)
        write_file(os.path.join(deck_dir_path, '.DS_Store'), 'Finder')
        write_file(os.path.join(deck_dir_path, 'rule_decks', '.DS_Store'), 'Finder')
        write_file(os.path.join(deck_dir_path, '.git', 'HEAD'), 'ref: refs/heads/main')
        self.assertEqual(['rule_decks/globals.lvs', 'sg13g2.lvs'],
                         sorted(deck_fingerprint(self.lvs_script_path).sha256_by_relative_path.keys()))

    def test_deck_follows_symbolic_links(self):
        # e.g. the ihp-sg13cmos5l rule decks, which link to those of ihp-sg13g2
        shared_path = os.path.join(self.tmp_dir, 'shared', 'shared.lvs')
        write_file(shared_path, 'v1')
        link_path = os.path.join(os.path.dirname(self.lvs_script_path), 'rule_decks', 'shared.lvs')
        os.symlink(shared_path, link_path)
        os.symlink(os.path.join(self.tmp_dir, 'missing.lvs'),
                   os.path.join(os.path.dirname(self.lvs_script_path), 'rule_decks', 'dangling.lvs'))
        before = deck_fingerprint(self.lvs_script_path)
        write_file(shared_path, 'v2')
        after = deck_fingerprint(self.lvs_script_path)
        self.assertNotIn('rule_decks/dangling.lvs', before.sha256_by_relative_path)
        self.assertNotEqual(before.sha256_by_relative_path['rule_decks/shared.lvs'],
                            after.sha256_by_relative_path['rule_decks/shared.lvs'])

    def test_same_inputs_at_other_paths_have_no_differences(self):
        # e.g. a reinstalled KPEX, a moved output directory
        other_script_path = self.make_deck(dir_name='other_deck')
        write_file(os.path.join(self.tmp_dir, 'moved', 'cell.gds'), 'layout')
        write_file(os.path.join(self.tmp_dir, 'moved', 'cell.spice'), '.subckt cell VDD VSS\n.ends\n')
        other = self.fingerprint(lvs_script_path=other_script_path,
                                 gds_path=os.path.join(self.tmp_dir, 'moved', 'cell.gds'),
                                 schematic_path=os.path.join(self.tmp_dir, 'moved', 'cell.spice'))
        self.assertEqual([], fingerprint_differences(self.fingerprint(), other))

    def test_changed_deck_file_is_named(self):
        cached = self.fingerprint()
        write_file(os.path.join(self.tmp_dir, 'deck', 'rule_decks', 'globals.lvs'), 'changed\n')
        self.assertEqual(["the LVS deck changed (rule_decks/globals.lvs)"],
                         fingerprint_differences(cached, self.fingerprint()))

    def test_added_and_removed_deck_files_are_named(self):
        cached = self.fingerprint()
        os.remove(os.path.join(self.tmp_dir, 'deck', 'rule_decks', 'globals.lvs'))
        write_file(os.path.join(self.tmp_dir, 'deck', 'rule_decks', 'custom_reader.lvs'), 'new\n')
        self.assertEqual(["the LVS deck changed (rule_decks/custom_reader.lvs, rule_decks/globals.lvs)"],
                         fingerprint_differences(cached, self.fingerprint()))

    def test_many_changed_deck_files_are_counted(self):
        cached = self.fingerprint()
        for i in range(7):
            write_file(os.path.join(self.tmp_dir, 'deck', 'rule_decks', f"new_{i}.lvs"), 'new\n')
        self.assertEqual(["the LVS deck changed (rule_decks/new_0.lvs, rule_decks/new_1.lvs, "
                          "rule_decks/new_2.lvs, rule_decks/new_3.lvs, rule_decks/new_4.lvs "
                          "and 2 more files)"],
                         fingerprint_differences(cached, self.fingerprint()))

    def test_changed_inputs_are_reported(self):
        cached = self.fingerprint()
        write_file(os.path.join(self.tmp_dir, 'other.gds'), 'other layout')
        write_file(os.path.join(self.tmp_dir, 'other.spice'), '.subckt other VDD VSS\n.ends\n')
        cases = [
            (dict(pdk='ihp-sg13cmos5l'), "the PDK changed (ihp-sg13g2 → ihp-sg13cmos5l)"),
            (dict(klayout_version='0.30.10'), "the KLayout version changed (0.30.12 → 0.30.10)"),
            (dict(klayout_version=''), "the KLayout version changed (0.30.12 → unknown)"),
            (dict(script_parameters={'run_mode': 'flat', 'no_simplify': 'true'}),
             "the LVS script parameters changed (run_mode: deep → flat)"),
            (dict(script_parameters={'run_mode': 'deep'}),
             "the LVS script parameters changed (no_simplify: true → unset)"),
            (dict(gds_path=os.path.join(self.tmp_dir, 'other.gds')), "the input layout changed"),
            (dict(cell_name='other'), "the cell changed (cell → other)"),
            (dict(schematic_path=os.path.join(self.tmp_dir, 'other.spice')), "the schematic changed"),
        ]
        for overrides, expected in cases:
            with self.subTest(expected):
                self.assertEqual([expected], fingerprint_differences(cached, self.fingerprint(**overrides)))

    def test_other_format_version_never_matches(self):
        cached = self.fingerprint()
        cached.format_version = FINGERPRINT_FORMAT_VERSION - 1
        self.assertEqual([f"the fingerprint format changed ({FINGERPRINT_FORMAT_VERSION - 1} → "
                          f"{FINGERPRINT_FORMAT_VERSION})"],
                         fingerprint_differences(cached, self.fingerprint()))

    def test_json_round_trip(self):
        path = os.path.join(self.tmp_dir, 'cell.lvs_fingerprint.pb.json')
        fingerprint = self.fingerprint()
        write_fingerprint(path, fingerprint)
        self.assertEqual(fingerprint, read_fingerprint(path))
        with open(path) as f:
            self.assertIn('"sha256_by_relative_path"', f.read())

    def test_missing_or_unreadable_fingerprint_is_none(self):
        path = os.path.join(self.tmp_dir, 'cell.lvs_fingerprint.pb.json')
        self.assertIsNone(read_fingerprint(path))
        write_file(path, '{"written_by_a_newer_kpex": 1}')
        self.assertIsNone(read_fingerprint(path))


@allure.parent_suite("Unit Tests")
@allure.tag("LVS", "KLayout")
class KpexCLILVSCacheTest(TempDirTestCase):
    def setUp(self):
        super().setUp()

        self.output_dir_path = os.path.join(self.tmp_dir, 'output', f"{CELL_NAME}__{CELL_NAME}")
        os.makedirs(self.output_dir_path)
        self.lvsdb_path = os.path.join(self.output_dir_path, f"{CELL_NAME}.lvsdb.gz")

        self.gds_path = os.path.join(self.tmp_dir, f"{CELL_NAME}.gds")
        write_file(self.gds_path, 'layout')
        schematic_path = os.path.join(self.output_dir_path, f"{CELL_NAME}_dummy_schematic.spice")
        write_file(schematic_path, f".subckt {CELL_NAME} VDD VSS\n.ends\n.end\n")

        self.args = argparse.Namespace(
            input_mode=InputMode.GDS,
            output_dir_path=self.output_dir_path,
            cache_dir_path=os.path.join(self.tmp_dir, 'output', '.kpex_cache'),
            cache_lvs=True,
            pdk='ihp-sg13g2',
            gds_path=self.gds_path,
            effective_gds_path=self.gds_path,
            effective_schematic_path=schematic_path,
            effective_cell_name=CELL_NAME,
            klayout_exe_path='klayout',
            lvs_script_path=self.make_deck(),
            klayout_lvs_verbose=False,
        )
        self.cache_entry = LVSCacheEntry(
            dir_path=os.path.join(self.args.cache_dir_path, self.args.pdk,
                                  os.path.splitroot(os.path.abspath(self.gds_path))[-1]),
            cell_name=CELL_NAME
        )

        patcher = mock.patch.object(Tool, 'detect_version', return_value=Version('0.30.12'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_cache_hit(self):
        self.cache_entry.store(lvsdb_path=CACHED_LVSDB_PATH,
                               fingerprint=KpexCLI.lvs_input_fingerprint(self.args))

    def create_lvsdb(self) -> Tuple[Any, FakeKLayoutLVS, mock.Mock]:
        fake_klayout = FakeKLayoutLVS()
        with mock.patch('klayout_pex.klayout.lvs_runner.subprocess.Popen', fake_klayout), \
             mock.patch('klayout_pex.kpex_cli.info') as info_mock:
            lvsdb = KpexCLI().create_lvsdb(self.args)
        return lvsdb, fake_klayout, info_mock

    def assert_cache_miss(self, reason: str, fake_klayout: FakeKLayoutLVS, info_mock: mock.Mock):
        self.assertEqual(1, fake_klayout.call_count)
        info_mock.assert_any_call(f"Cache miss: {reason}")
        # the new LVS database is cached, together with its fingerprint
        self.assertTrue(filecmp.cmp(self.lvsdb_path, self.cache_entry.lvsdb_path, shallow=False))
        self.assertEqual(KpexCLI.lvs_input_fingerprint(self.args),
                         read_fingerprint(self.cache_entry.fingerprint_path))

    def test_cache_hit_reads_the_cached_lvsdb(self):
        self.make_cache_hit()
        # left over from an earlier run in the same output directory
        write_file(self.lvsdb_path, '#%lvsdb-klayout\n')

        lvsdb, fake_klayout, _ = self.create_lvsdb()

        self.assertEqual(0, fake_klayout.call_count)
        self.assertEqual(CELL_NAME, lvsdb.internal_top_cell().name)
        self.assertTrue(filecmp.cmp(self.cache_entry.lvsdb_path, self.lvsdb_path, shallow=False))

    def test_cache_hit_without_earlier_run_in_the_output_directory(self):
        # e.g. a CI run with a restored cache directory
        self.make_cache_hit()

        lvsdb, fake_klayout, _ = self.create_lvsdb()

        self.assertEqual(0, fake_klayout.call_count)
        self.assertEqual(CELL_NAME, lvsdb.internal_top_cell().name)

    def test_cache_hit_with_a_new_modification_time_of_the_layout(self):
        # e.g. a fresh checkout
        self.make_cache_hit()
        os.utime(self.gds_path)

        _, fake_klayout, _ = self.create_lvsdb()

        self.assertEqual(0, fake_klayout.call_count)

    def test_cache_miss_without_cached_lvsdb(self):
        _, fake_klayout, info_mock = self.create_lvsdb()
        self.assert_cache_miss("there is no cached LVSDB", fake_klayout, info_mock)

    def test_cache_miss_for_cached_lvsdb_without_fingerprint(self):
        # e.g. cached by an earlier KPEX, like the IHP RF MOS devices without layout geometry
        os.makedirs(self.cache_entry.dir_path)
        shutil.copy(CACHED_LVSDB_PATH, self.cache_entry.lvsdb_path)

        _, fake_klayout, info_mock = self.create_lvsdb()

        self.assert_cache_miss("the cached LVSDB has no fingerprint of its LVS inputs", fake_klayout, info_mock)

    def test_cache_miss_after_a_deck_change(self):
        self.make_cache_hit()
        write_file(os.path.join(self.tmp_dir, 'deck', 'rule_decks', 'globals.lvs'), 'changed\n')

        _, fake_klayout, info_mock = self.create_lvsdb()

        self.assert_cache_miss("the LVS deck changed (rule_decks/globals.lvs)", fake_klayout, info_mock)

    def test_cache_miss_after_a_klayout_upgrade(self):
        self.make_cache_hit()

        with mock.patch.object(Tool, 'detect_version', return_value=Version('0.30.13')):
            _, fake_klayout, info_mock = self.create_lvsdb()
            self.assert_cache_miss("the KLayout version changed (0.30.12 → 0.30.13)", fake_klayout, info_mock)
