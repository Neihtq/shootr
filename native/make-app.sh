#!/bin/zsh
# Bundle the SwiftPM binary into a minimal .app so it launches from Finder
# with a proper GUI session (unsandboxed, developer-signed — design 12 §6).
set -e
cd "$(dirname "$0")"

swift build -c release
APP=ShootrApp.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>ShootrApp</string>
  <key>CFBundleIdentifier</key><string>dev.shootr.app</string>
  <key>CFBundleName</key><string>Shootr</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>15.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

cp .build/release/ShootrApp "$APP/Contents/MacOS/"
codesign --force --sign - "$APP"
echo "built $PWD/$APP — open it with: open $APP"
