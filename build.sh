#! /bin/bash

DIR=$(dirname -- $(realpath ${BASH_SOURCE}))

function printUsageAndBail() {
	echo "Usage: $0 (debug|release)"
	exit 1
}

if [[ $# -lt 1 ]]
then
	printUsageAndBail
fi

CMAKE_OPTIONS=""

case $1 in
	debug)
		BUILD_TARGET=Debug
		;;
	release)
		BUILD_TARGET=RelWithDbgInfo
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

BUILD_DIR=build/kpex_$BUILD_TARGET
mkdir -p $BUILD_DIR
pushd $BUILD_DIR

cmake -G "Unix Makefiles" \
 	  -DCMAKE_BUILD_TYPE=$BUILD_TARGET \
	  $CMAKE_OPTIONS \
	  $DIR

make

popd

