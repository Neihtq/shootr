"""Shootr cross-platform analyzer (design 13).

Implements the same JSONL contract as the Swift helper (design 03 §4, and the
contract *as actually implemented* in helper/Sources — where they differ, the
implementation wins: flat top-level `embedding`+`embedding_dim`, `clipped_hi/lo`
directly under `frame`). The engine swaps analyzers via the SHOOTR_HELPER env
var and never knows which one produced a row except through `engine_version`.

One measurement semantics everywhere: this analyzer must behave identically on
macOS, Windows, and Linux. Anything platform-conditional belongs in execution-
provider selection (models.py), never in what gets measured.
"""

ANALYZER_VERSION = "py-0.1.0"
