#! /bin/bash
##
## --------------------------------------------------------------------------------
## SPDX-FileCopyrightText: 2024-2026 Martin Jan Köhler and Harald Pretl
## Johannes Kepler University, Institute for Integrated Circuits.
##
## This file is part of KPEX
## (see https://github.com/iic-jku/kpex).
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

# Generates the files KPEX needs besides its sources (both are .gitignore'd, but packaged):
#   - the protobuf python modules kpex_protobuf/**/*_pb2.py, from protos/**/*.proto,
#     using the protoc bundled with grpcio-tools (see the build dependency group in pyproject.toml)
#   - the tech info of the bundled PDKs kpex_protobuf/*_tech.pb.json (see scripts/gen_tech_pb)

DIR=$(dirname -- $(realpath ${BASH_SOURCE}))
cd "$DIR" || exit 1

if [[ $# -gt 0 ]]
then
	echo "Usage: $0"
	exit 1
fi

set -x
set -e

poetry run python scripts/build/generate_protobuf.py

poetry run python scripts/gen_tech_pb kpex_protobuf
