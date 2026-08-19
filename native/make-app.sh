#!/bin/zsh
# Bundle the SwiftPM binary into a .app.
#
#   ./make-app.sh            — light bundle (engine must run separately)
#   ./make-app.sh --bundled  — self-contained: embedded Python + engine +
#                              helper + web UI. Double-click and everything
#                              runs. ~120 MB.
set -e
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"

# Relocatable CPython (python-build-standalone). Pinned for reproducibility
# (verified against the GitHub releases API, 2026-08).
PBS_VERSION="20260814"
PBS_PYTHON="3.14.7"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PBS_PYTHON}+${PBS_VERSION}-aarch64-apple-darwin-install_only.tar.gz"
PBS_CACHE="$ROOT/.cache/python-standalone-${PBS_PYTHON}.tar.gz"

swift build -c release
APP=ShootrApp.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

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

if [[ "$1" == "--bundled" ]]; then
  RES="$APP/Contents/Resources"

  echo "→ embedded Python (python-build-standalone ${PBS_PYTHON})"
  if [[ ! -f "$PBS_CACHE" ]]; then
    mkdir -p "$(dirname "$PBS_CACHE")"
    curl -fL --progress-bar -o "$PBS_CACHE" "$PBS_URL"
  fi
  tar -xzf "$PBS_CACHE" -C "$RES"   # extracts to Resources/python/

  echo "→ engine + dependencies"
  mkdir -p "$RES/engine"
  cp -R "$ROOT/engine/shootr" "$RES/engine/"
  find "$RES/engine" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
  "$RES/python/bin/python3" -m pip install --quiet --no-warn-script-location \
    --target "$RES/engine" fastapi uvicorn blake3

  echo "→ Swift helper"
  (cd "$ROOT/helper" && swift build -c release >/dev/null)
  cp "$ROOT/helper/.build/release/shootr-analyze" "$RES/"

  echo "→ web UI"
  if [[ ! -f "$ROOT/web/dist/index.html" ]]; then
    (cd "$ROOT/web" && npm run build >/dev/null)
  fi
  cp -R "$ROOT/web/dist" "$RES/web-dist"
fi

codesign --force --deep --sign - "$APP"
du -sh "$APP" | awk '{print "built " $2 " (" $1 ")"}'
echo "open it with: open $PWD/$APP"
