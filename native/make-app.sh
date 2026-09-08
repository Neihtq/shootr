#!/bin/zsh
# Bundle the SwiftPM binary into a .app.
#
#   ./make-app.sh                          — light bundle (engine runs separately)
#   ./make-app.sh --bundled                — self-contained, for THIS Mac
#   ./make-app.sh --bundled --arch x86_64   — self-contained, for Intel Macs
#
# One .app per architecture rather than a universal binary: a universal build
# needs `swift build --arch arm64 --arch x86_64`, which requires full Xcode
# (xcbuild). This project builds with CLI tools only, and single-arch
# cross-compiles work fine, so a second bundle is the path that exists here.
set -e
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"

HOST_ARCH="$(uname -m)"
# A host interpreter with tomllib (3.11+) — the CLI-tools python3 is 3.9 and
# cannot read pyproject, which is where the dependency list lives.
for cand in "$ROOT/.venv/bin/python3" python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 && \
     "$cand" -c "import tomllib" >/dev/null 2>&1; then HOSTPY="$cand"; break; fi
done
ARCH="$HOST_ARCH"
BUNDLED=0
want_arch=0
for arg in "$@"; do
  if (( want_arch )); then ARCH="$arg"; want_arch=0; continue; fi
  case "$arg" in
    --bundled) BUNDLED=1 ;;
    --arch) want_arch=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
[[ "$ARCH" == "arm64" || "$ARCH" == "x86_64" ]] || \
  { echo "--arch must be arm64 or x86_64 (got '$ARCH')" >&2; exit 2; }

# Relocatable CPython (python-build-standalone). Pinned for reproducibility
# (verified against the GitHub releases API, 2026-08).
PBS_VERSION="20260814"
PBS_PYTHON="3.14.7"
# python-build-standalone calls arm64 "aarch64"; Swift and uname say "arm64".
[[ "$ARCH" == "arm64" ]] && PBS_ARCH="aarch64" || PBS_ARCH="$ARCH"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PBS_PYTHON}+${PBS_VERSION}-${PBS_ARCH}-apple-darwin-install_only.tar.gz"
PBS_CACHE="$ROOT/.cache/python-standalone-${PBS_PYTHON}-${PBS_ARCH}.tar.gz"

# A cross-built bundle gets its own name, so it can never overwrite the app you
# actually run and the file you hand someone says which Mac it is for.
if [[ "$ARCH" == "$HOST_ARCH" ]]; then APP=ShootrApp.app
else APP="ShootrApp-${ARCH}.app"; fi

swift build -c release --arch "$ARCH"
BIN=".build/${ARCH}-apple-macosx/release/ShootrApp"
[[ -f "$BIN" ]] || BIN=".build/release/ShootrApp"

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

cp "$BIN" "$APP/Contents/MacOS/ShootrApp"

if [[ "$BUNDLED" == 1 ]]; then
  RES="$APP/Contents/Resources"

  echo "→ embedded Python (python-build-standalone ${PBS_PYTHON}, ${PBS_ARCH})"
  if [[ ! -f "$PBS_CACHE" ]]; then
    mkdir -p "$(dirname "$PBS_CACHE")"
    curl -fL --progress-bar -o "$PBS_CACHE" "$PBS_URL"
  fi
  tar -xzf "$PBS_CACHE" -C "$RES"   # extracts to Resources/python/

  echo "→ engine + dependencies"
  mkdir -p "$RES/engine"
  if [[ "$ARCH" == "$HOST_ARCH" ]]; then
    # Install the ENGINE PACKAGE, so its dependencies come from pyproject.toml
    # rather than a list duplicated here. The hardcoded list silently omitted
    # numpy when style learning landed, which would have shipped an .app whose
    # engine could not import.
    "$RES/python/bin/python3" -m pip install --quiet --no-warn-script-location \
      --target "$RES/engine" "$ROOT/engine"
  else
    # Cross-arch: the bundled interpreter cannot run on this Mac, and pip
    # refuses --platform for a source tree. So copy the package and fetch
    # wheels for the TARGET arch — with the dependency list read out of
    # pyproject rather than retyped, or it drifts again.
    cp -R "$ROOT/engine/shootr" "$RES/engine/"
    [[ -n "$HOSTPY" ]] || { echo "need a python3.11+ to read pyproject" >&2; exit 1; }
    DEPS=$("$HOSTPY" -c "
import tomllib
with open('$ROOT/engine/pyproject.toml','rb') as f:
    print(' '.join(tomllib.load(f)['project']['dependencies']))")
    echo "   wheels for ${ARCH}: ${DEPS}"
    "$HOSTPY" -m pip install --quiet --no-warn-script-location \
      --target "$RES/engine" --platform "macosx_11_0_${ARCH}" \
      --python-version 3.14 --only-binary=:all: ${=DEPS}
  fi
  find "$RES/engine" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

  echo "→ Swift helper"
  (cd "$ROOT/helper" && swift build -c release --arch "$ARCH" >/dev/null)
  HELPER="$ROOT/helper/.build/${ARCH}-apple-macosx/release/shootr-analyze"
  [[ -f "$HELPER" ]] || HELPER="$ROOT/helper/.build/release/shootr-analyze"
  cp "$HELPER" "$RES/"

  echo "→ web UI"
  if [[ ! -f "$ROOT/web/dist/index.html" ]]; then
    (cd "$ROOT/web" && npm run build >/dev/null)
  fi
  cp -R "$ROOT/web/dist" "$RES/web-dist"

  # Every arch-specific file must really BE the target arch. Getting this wrong
  # fails on the recipient's Mac with an error they cannot act on, so check it
  # here where it is cheap.
  for f in "$APP/Contents/MacOS/ShootrApp" "$RES/shootr-analyze" \
           "$RES/python/bin/python3"; do
    got=$(lipo -archs "$f" 2>/dev/null || echo "?")
    [[ "$got" == *"$ARCH"* ]] || \
      { echo "ABORT: $f is '$got', expected $ARCH" >&2; exit 1; }
  done
fi

codesign --force --deep --sign - "$APP"
du -sh "$APP" | awk '{print "built " $2 " (" $1 ")"}'
if [[ "$ARCH" != "$HOST_ARCH" ]]; then
  echo "NOTE: $ARCH build — it cannot be launched on this $HOST_ARCH Mac."
  echo "      Copy it by USB or scp (not AirDrop) to skip Gatekeeper quarantine."
else
  echo "open it with: open $PWD/$APP"
fi
