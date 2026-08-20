"""Cross-client parity: the two frontends must bind the same keys and explain
the engine the same way.

There is no shared code between SwiftUI and React, so nothing but a test stops
them drifting — and drift here is user-visible in the worst way: the same
keystroke doing different things in the two apps, or one client explaining a
verdict the other doesn't. Design 12 §3 states the parity requirement; this
enforces the mechanical part of it by reading both sources.

Deliberately narrow. It checks the key bindings, the action-bar hint strip, and
that both shortcut references exist and name the same overlays — not prose
equality, which would fail on every wording tweak and get deleted.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE_VIEWS = ROOT / "native/Sources/ShootrApp/Views.swift"
WEB_KEYBOARD = ROOT / "web/src/keyboard.ts"
WEB_SHORTCUTS = ROOT / "web/src/components/ShortcutsDialog.tsx"

pytestmark = pytest.mark.skipif(
    not NATIVE_VIEWS.exists() or not WEB_KEYBOARD.exists(),
    reason="client sources not present",
)

# Character keys both clients must bind to the same action. Arrows/space/home
# are excluded: they're keyCodes in AppKit and names in the browser, so
# comparing the literals proves nothing.
SHARED_CHAR_KEYS = {"j", "k", "g", "G", "p", "a", "x", "e", "s", "o", "c", "?"}


def _native_char_keys() -> set[str]:
    # The charactersIgnoringModifiers switch in KeyCatcher.handle. Each arm is
    # `case "x":` or `case "?", "/":`.
    body = NATIVE_VIEWS.read_text().split("charactersIgnoringModifiers", 1)[1]
    body = body.split("default:", 1)[0]
    keys: set[str] = set()
    for arm in re.findall(r"case ([^:]+):", body):
        keys.update(re.findall(r'"([^"]+)"', arm))
    return keys


def _web_char_keys() -> set[str]:
    src = WEB_KEYBOARD.read_text()
    return {k for k in re.findall(r'case "([^"]+)":', src) if len(k) == 1}


def test_both_clients_bind_the_same_character_keys():
    """A key that culls in one app and does nothing in the other is worse than
    no binding: muscle memory built in one client silently fails in the other.
    """
    native = _native_char_keys()
    web = _web_char_keys()
    assert SHARED_CHAR_KEYS <= native, f"native missing {SHARED_CHAR_KEYS - native}"
    assert SHARED_CHAR_KEYS <= web, f"web missing {SHARED_CHAR_KEYS - web}"


def test_unshifted_slash_also_opens_the_shortcut_list():
    """`?` is shift-/ on US layouts but not on every layout, so the unshifted
    key has to work too — otherwise the in-app help is unreachable by keyboard
    for some users."""
    assert '"?", "/"' in NATIVE_VIEWS.read_text()
    web = WEB_KEYBOARD.read_text()
    assert 'case "?":' in web and 'case "/":' in web


def test_action_bar_hint_strips_match():
    """The always-visible strip is the discovery path for everything else; if
    the two clients advertise different keys, one of them is lying."""
    native = re.findall(
        r'Item\("([^"]+)", "([^"]+)"\)',
        NATIVE_VIEWS.read_text().split("static let strip", 1)[1],
    )
    # Slice to the end of the array literal — note the `Item[]` annotation
    # means the first "]" after the name is NOT the array's closing bracket.
    decl = WEB_SHORTCUTS.read_text().split("export const STRIP", 1)[1]
    web = re.findall(
        r'key: "([^"]+)", label: "([^"]+)"',
        decl.split("\n];", 1)[0],
    )
    assert native == web, f"strip drift: native={native} web={web}"


def test_both_shortcut_references_name_the_overlays_and_the_verdict_rules():
    """The `?` panel is where a user learns that pick/alt/reject are proposed
    automatically and that the red heatmap is per-frame-relative. A client
    missing that explanation leaves the same questions unanswered that prompted
    building it (user-reported: "some red rectangles appear, what's that?")."""
    for path in (NATIVE_VIEWS, WEB_SHORTCUTS):
        text = path.read_text().lower()
        assert "sharpness heatmap" in text, path
        assert "focus landed" in text, path
        assert "composition overlay" in text, path
        # The verdict explanation: automatic, floor-abstains, never deletes.
        assert "automatically" in text, path
        assert "quality floor" in text, path
        assert "never culled" in text, path
        assert "deleted" in text, path
