"""Model registry — download-on-first-run with checksums (design 13 §3).

Same pattern as native/make-app.sh's bundled-Python download: fetch once into
a cache directory, verify, reuse forever. The registry hash feeds
`engine_version`, so swapping a weight automatically invalidates analysis rows
(design 01 invariant: engine_version is the re-analysis key).

Tier policy (design 13 §2.1): entries marked tier="accuracy" are the
accuracy-first picks; tier="floor" are the compatibility floor. An accuracy
entry whose artifact URL isn't pinned yet (sha256=None) is INACTIVE — the
floor entry for the same component loads instead, and `verify-models` says so
out loud. No silent downgrades, no fabricated URLs.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelSpec:
    component: str   # "face_detect" | "face_id" | "blink" | "scene_embedding" | "saliency"
    name: str
    tier: str        # "accuracy" | "floor"
    url: str | None
    sha256: str | None       # of the downloaded artifact (archive if archived)
    filename: str            # final cached file name
    archive_member: str | None = None  # extract this member from a zip at url
    member_sha256: str | None = None   # of the extracted member

    @property
    def active(self) -> bool:
        return self.url is not None


# Pinned artifacts. Checksums verified at pin time; a mismatch at download
# time is an error, never a warning. Accuracy-tier entries without official
# ONNX artifacts start unpinned (url/sha256 None) per design 13 §2.1 — the
# floor runs until they're validated and pinned.
REGISTRY: list[ModelSpec] = [
    # -- Face detection ------------------------------------------------------
    # det_10g from the official InsightFace buffalo_l pack IS the SCRFD-10G
    # detector — the accuracy-first pick with an official artifact. Archive +
    # member hashes verified 2026-08-20.
    ModelSpec(
        "face_detect", "scrfd_10g_buffalo_l", "accuracy",
        url="https://github.com/deepinsight/insightface/releases/download/"
            "v0.7/buffalo_l.zip",
        sha256="80ffe37d8a5940d59a7384c201a2a38d"
               "4741f2f3c51eef46ebb28218a7b0ca2f",
        filename="scrfd_det_10g.onnx",
        archive_member="det_10g.onnx",
        member_sha256="5838f7fe053675b1c7a08b633df49e7a"
                      "f5495cee0493c7dcf6697200b85b5b91",
    ),
    # -- Face identity -------------------------------------------------------
    ModelSpec(
        "face_id", "adaface_ir101_webface12m", "accuracy",
        url=None, sha256=None,  # TODO(pin): community ONNX export, validate first
        filename="adaface_ir101.onnx",
    ),
    # w600k_r50 (ArcFace R50) from the same official pack — the floor that
    # runs until AdaFace is validated and pinned.
    ModelSpec(
        "face_id", "arcface_w600k_r50", "floor",
        url="https://github.com/deepinsight/insightface/releases/download/"
            "v0.7/buffalo_l.zip",
        sha256="80ffe37d8a5940d59a7384c201a2a38d"
               "4741f2f3c51eef46ebb28218a7b0ca2f",
        filename="arcface_w600k_r50.onnx",
        archive_member="w600k_r50.onnx",
        member_sha256="4c06341c33c2ca1f86781dab0e829f88"
                      "ad5b64be9fba56e56bc9ebdefc619e43",
    ),
    # -- Blink (MediaPipe task bundle, not ONNX) ------------------------------
    ModelSpec(
        "blink", "mediapipe_face_landmarker_v2", "accuracy",
        # Versioned (not 'latest') artifact; hash verified 2026-08-20.
        url="https://storage.googleapis.com/mediapipe-models/face_landmarker/"
            "face_landmarker/float16/1/face_landmarker.task",
        sha256="64184e229b263107bc2b804c6625db1341"
               "ff2bb731874b0bcc2fe6544e0bc9ff",
        filename="face_landmarker.task",
    ),
    # -- Scene embedding -----------------------------------------------------
    # onnx-community exports of Meta's DINOv2-with-registers, pinned to the
    # repo commit (immutable ref); hashes verified 2026-08-20. ViT-L/14 is
    # the accuracy-first pick (design 13 §2.1), ~1.2 GB fp32.
    ModelSpec(
        "scene_embedding", "dinov2_vitl14_reg", "accuracy",
        url="https://huggingface.co/onnx-community/dinov2-with-registers-large/"
            "resolve/e91ea061a0cb94e6bb9d4b6d8d55ba2bba2287d3/onnx/model.onnx",
        sha256="b6212f2508f883b6f277c53d05b630cf"
               "24f7977fd1ab350a25751fdbf2cf233f",
        filename="dinov2_vitl14_reg.onnx",
    ),
    ModelSpec(
        "scene_embedding", "dinov2_vits14_reg", "floor",
        url="https://huggingface.co/onnx-community/dinov2-with-registers-small/"
            "resolve/ec7abea1a8757ec4f9f7b26399d31234ffaa6e6a/onnx/model.onnx",
        sha256="815e440d222e60294bb5b165491c4760"
               "e7f08dc7ecd2488a5450e93d50887efe",
        filename="dinov2_vits14_reg.onnx",
    ),
    # -- Saliency / subject --------------------------------------------------
    # Official BiRefNet ONNX release assets; hashes verified 2026-08-20/21.
    # The 512² fp16 variant is deliberately preferred over the 1024² full
    # model: the engine consumes only a centroid + coarse bbox (primary-
    # subject selection, thirds/headroom flags), and on real shoot frames
    # the two produce equivalent boxes while 512-fp16 runs 5x faster
    # (1.07 s vs 5.03 s/photo CPU — was 70% of the entire analyze budget).
    # Not a floor fallback: it IS the right tool for a bbox consumer.
    ModelSpec(
        "saliency", "birefnet_general_512_fp16", "accuracy",
        url="https://github.com/ZhengPeng7/BiRefNet/releases/download/v1/"
            "BiRefNet-general-resolution_512x512-fp16-epoch_216.onnx",
        sha256="18b64a270d3abe7d36e665500c3f2413"
               "6bcaf7616771b4cb21c6e8c57fec7237",
        filename="birefnet_512_fp16.onnx",
    ),
]


def registry_hash() -> str:
    """8-char digest over the pinned registry — part of engine_version, so a
    weight swap re-analyzes everything (design 13 §1: swaps get costlier the
    later they happen; make them visible)."""
    blob = json.dumps(
        [(m.component, m.name, m.sha256) for m in REGISTRY if m.active],
        sort_keys=True,
    ).encode()
    return hashlib.sha256(blob).hexdigest()[:8]


def cache_dir() -> Path:
    if env := os.environ.get("SHOOTR_MODEL_DIR"):
        return Path(env)
    if platform.system() == "Darwin":
        base = Path.home() / "Library" / "Caches"
    elif platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "shootr" / "models"


def resolve(component: str) -> ModelSpec | None:
    """Active accuracy-tier spec for a component, else its floor, else None.
    None means the component abstains (emits nothing) rather than guessing."""
    specs = [m for m in REGISTRY if m.component == component]
    for tier in ("accuracy", "floor"):
        for m in specs:
            if m.tier == tier and m.active:
                return m
    return None


def ensure(spec: ModelSpec) -> Path:
    """Return the local path, downloading + verifying on first use.
    Cached files are verified against the MEMBER hash (what we run), the
    download against the ARCHIVE hash (what we fetched)."""
    dest = cache_dir() / spec.filename
    file_hash = spec.member_sha256 or spec.sha256
    if dest.exists():
        if file_hash and _sha256(dest) != file_hash:
            raise RuntimeError(
                f"cached model {spec.filename} fails checksum — delete "
                f"{dest} and retry")
        return dest
    if not spec.url:
        raise RuntimeError(f"model {spec.name} has no pinned artifact")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {spec.name} → {dest}", file=sys.stderr)
    urllib.request.urlretrieve(spec.url, tmp)  # noqa: S310 — pinned https URLs
    if spec.sha256 and _sha256(tmp) != spec.sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded {spec.name} fails checksum")
    if spec.archive_member:
        _extract_member(tmp, spec, dest)
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(dest)  # atomic: a killed download never half-installs
    return dest


def _extract_member(archive: Path, spec: ModelSpec, dest: Path) -> None:
    import zipfile

    with zipfile.ZipFile(archive) as zf:
        with zf.open(spec.archive_member) as src, \
                open(dest.with_suffix(".extract"), "wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)
    tmp = dest.with_suffix(".extract")
    if spec.member_sha256 and _sha256(tmp) != spec.member_sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"extracted {spec.archive_member} fails checksum")
    tmp.replace(dest)


def ort_providers() -> list[str]:
    """Execution-provider preference. Platform-conditional is ALLOWED here —
    EPs change speed, never measured values (design 13 §6 determinism note).

    macOS defaults to CPU, deliberately: measured 2026-08-20 on the M4-class
    floor machine, the CoreML EP fragmented DINOv2 ViT-L into 171 partitions
    and spent ~20 MINUTES compiling before failing, while CPU loads in ~1 s
    and infers in ~1.5 s/photo. That is the doc-13 "CoreML coverage must be
    measured, not assumed" outcome. Opt back in per-session with
    SHOOTR_ORT_PROVIDERS=CoreMLExecutionProvider,CPUExecutionProvider."""
    import onnxruntime as ort

    available = set(ort.get_available_providers())
    if env := os.environ.get("SHOOTR_ORT_PROVIDERS"):
        wanted = [p.strip() for p in env.split(",") if p.strip()]
        return [p for p in wanted if p in available] or ["CPUExecutionProvider"]
    preferred = ([] if platform.system() == "Darwin"
                 else ["CUDAExecutionProvider", "DmlExecutionProvider"])
    return [p for p in preferred if p in available] + ["CPUExecutionProvider"]


def load_session(component: str):
    """onnxruntime session for a component, or None if nothing is pinned.
    Callers treat None as 'abstain' — a missing model produces absent fields,
    never zeros (null ≠ 0, design 04 §5)."""
    spec = resolve(component)
    if spec is None or spec.filename.endswith(".task"):
        return None
    import onnxruntime as ort

    path = str(ensure(spec))
    try:
        return ort.InferenceSession(path, providers=ort_providers())
    except Exception:  # noqa: BLE001 — EP compile can fail (sandboxed tmp,
        # missing CUDA runtime); CPU changes speed, never measured values.
        print(f"{component}: accelerated provider failed, using CPU",
              file=sys.stderr)
        return ort.InferenceSession(path,
                                    providers=["CPUExecutionProvider"])


def verify_report() -> list[dict]:
    """One row per component: what's active, what tier, what's still TODO —
    the honesty surface for `shootr-analyze-py verify-models`."""
    rows = []
    for component in sorted({m.component for m in REGISTRY}):
        spec = resolve(component)
        rows.append({
            "component": component,
            "active": spec.name if spec else None,
            "tier": spec.tier if spec else None,
            "cached": bool(spec and (cache_dir() / spec.filename).exists()),
            "pinned": bool(spec and spec.sha256),
            "unavailable": [m.name for m in REGISTRY
                            if m.component == component and not m.active],
        })
    return rows


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
