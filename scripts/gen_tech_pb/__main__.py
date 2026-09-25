#! /usr/bin/env python3
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
Generate the KPEX tech info JSON files <tech>_tech.pb.json of the bundled PDKs.

The PDK specifics (layers, process stack, parasitics) are defined here, not in the KPEX runtime,
which only reads the generated tech info files (klayout_pex_protobuf/*_tech.pb.json).

Requires the generated protobuf python modules (klayout_pex_protobuf/**/*_pb2.py), see gen_tech_pb.sh.

Usage:
    python scripts/gen_tech_pb OUTPUT_DIR
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT))  # for klayout_pex_protobuf

import google.protobuf.json_format

from tech_builder import Technology
import gf180mcuD
import ihp_sg13
import sky130A


def write_tech(output_directory: Path, tech: Technology):
    json_pb_path = output_directory / f"{tech.name}_tech.pb.json"
    print(f"Writing technology protobuf message to file '{json_pb_path}' in JSON format.")
    json_str = google.protobuf.json_format.MessageToJson(tech,
                                                         preserving_proto_field_name=True,
                                                         ensure_ascii=False)
    json_pb_path.write_text(json_str, encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the KPEX tech info JSON files of the bundled PDKs")
    parser.add_argument('output_directory', type=Path,
                        help="e.g. klayout_pex_protobuf")
    args = parser.parse_args()

    output_directory: Path = args.output_directory
    if output_directory.exists() and not output_directory.is_dir():
        print("ERROR: Output directory path already exists, but is not a directory", file=sys.stderr)
        return 2
    output_directory.mkdir(parents=True, exist_ok=True)

    for tech in (gf180mcuD.build_tech(),
                 sky130A.build_tech(),
                 ihp_sg13.build_tech(ihp_sg13.LayerStackVariant.SG13G2),
                 ihp_sg13.build_tech(ihp_sg13.LayerStackVariant.SG13CMOS5L)):
        write_tech(output_directory, tech)

    return 0


if __name__ == '__main__':
    sys.exit(main())
