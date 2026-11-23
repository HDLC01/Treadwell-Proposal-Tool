#!/bin/bash
# Builds "Treadwell Call Test.app" with the command-line Swift compiler (no Xcode project) and
# packs it as a zip. Runs on GitHub's Mac machines (.github/workflows/call-test-mac.yml); nobody
# at Treadwell needs a Mac or Xcode. Signed "ad hoc" (no Apple Developer account), so the first
# open needs System Settings > Privacy & Security > Open Anyway, once.
set -euo pipefail
cd "$(dirname "$0")"

APP="build/Treadwell Call Test.app"
rm -rf build
mkdir -p "$APP/Contents/MacOS"

swiftc -O -swift-version 5 -parse-as-library \
  -target arm64-apple-macos14.4 \
  Sources/*.swift \
  -o "$APP/Contents/MacOS/TreadwellCallTest"

cp Info.plist "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"

codesign --force --sign - --timestamp=none "$APP"
codesign --verify --strict --verbose=2 "$APP"

cd build
ditto -c -k --keepParent "Treadwell Call Test.app" "Treadwell-Call-Test.zip"
ls -l "Treadwell-Call-Test.zip"
