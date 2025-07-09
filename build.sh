#! /bin/bash
##
## --------------------------------------------------------------------------------
## SPDX-FileCopyrightText: 2024-2025 Martin Jan Köhler and Harald Pretl
## Johannes Kepler University, Institute for Integrated Circuits.
##
## This file is part of KPEX 
## (see https://github.com/martinjankoehler/klayout-pex).
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

DIR=$(dirname -- $(realpath ${BASH_SOURCE}))

function printUsageAndBail() {
	echo "Usage: $0 (debug|release|xcode)"
	exit 1
}

if [[ $# -lt 1 ]]
then
	printUsageAndBail
fi

BUILD_ARG="$1"

CMAKE_OPTIONS=""
CMAKE_GENERATOR=""

case "$BUILD_ARG" in
	debug)
		CMAKE_GENERATOR="Unix Makefiles"
		BUILD_TARGET=Debug
		;;
	release)
		CMAKE_GENERATOR="Unix Makefiles"
		BUILD_TARGET=RelWithDbgInfo
		;;
        xcode)
                CMAKE_GENERATOR="Xcode"                
                BUILD_TARGET=Debug
                ;;    
	*)
		echo "Unknown option $1"
		printUsageAndBail
		;;
esac

# hack for IIC compute servers (user-built protobuf)
if [[ -x $HOME/usr_local/bin/protoc ]]
then
	CMAKE_OPTIONS="$CMAKE_OPTIONS -DCMAKE_PREFIX_PATH=$HOME/usr_local"
fi

set -x
set -e

BUILD_DIR=build/kpex_$BUILD_ARG
mkdir -p $BUILD_DIR
pushd $BUILD_DIR

cmake -G "${CMAKE_GENERATOR}" \
 	  -DCMAKE_BUILD_TYPE=$BUILD_TARGET \
	  $CMAKE_OPTIONS \
	  $DIR

case "$CMAKE_GENERATOR" in
	"Unix Makefiles")
		make
		;;
	"Xcode")
		open *.xcodeproj
		;;
	*)
		;;
esac

popd

