#! /bin/bash
##
## --------------------------------------------------------------------------------
## SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
## Johannes Kepler University, Institute for Integrated Circuits.
##
## This file is part of KPEX 
## (see https://github.com/iic-jku/klayout-pex).
##
## This program is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program. If not, see <http://www.gnu.org/licenses/>.
## SPDX-License-Identifier: GPL-3.0-or-later
## --------------------------------------------------------------------------------
##

# Runs the smoke tests (tests/smoke) against the *installed* wheel, see tests/smoke/README.md
#
# NOTE: always (re)builds everything the wheel packages, so the tests never run against outdated files
#       (checking modification times isn't reliable, e.g. git operations touch sources):
#       - protobuf modules klayout_pex_protobuf/**/*_pb2.py and
#         PDK tech info klayout_pex_protobuf/*_tech.pb.json (./gen_tech_pb.sh, a few seconds)
#       - the wheel itself (a few seconds)

DIR=$(dirname -- $(realpath ${BASH_SOURCE}))
cd "$DIR" || exit 1

WHEEL_DIR="$DIR/build/smoke-tests-dist"

./gen_tech_pb.sh || exit 1

rm -rf "$WHEEL_DIR"
poetry build --format wheel --output "$WHEEL_DIR" || exit 1

KPEX_SMOKE_TEST_WHEEL=$(ls "$WHEEL_DIR"/klayout_pex-*.whl)
export KPEX_SMOKE_TEST_WHEEL

source "$DIR"/_run_tests.sh

run_tests "smoke" --no-coverage
