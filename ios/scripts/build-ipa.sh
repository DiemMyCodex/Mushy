#!/bin/sh
# builds an unsigned Mushy.ipa that sidestore or altstore signs and installs on the phone
set -e
cd "$(dirname "$0")/.."

CONFIG="${1:-Release}"
rm -rf build/Payload build/Mushy.ipa

xcodebuild -project Mushy.xcodeproj -target Mushy -configuration "$CONFIG" -sdk iphoneos \
    SYMROOT="$PWD/build" CODE_SIGNING_ALLOWED=NO -quiet build

mkdir -p build/Payload
cp -R "build/$CONFIG-iphoneos/Mushy.app" build/Payload/
(cd build && zip -qry Mushy.ipa Payload)
echo "built $PWD/build/Mushy.ipa"
