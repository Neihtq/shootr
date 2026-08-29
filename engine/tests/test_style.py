"""Style-learning tests (design 08): family discovery, k-NN prediction with
clamping, and the abstention guardrails. Synthetic data — the real-catalog
numbers live in docs/benchmarks (leave-one-group-out eval).
"""

import numpy as np
import pytest

from shootr.style import (TONAL_PARAMS, Prediction, StyleSample,
                          cluster_families, family_median, family_traits,
                          predict)

DIM = 16
EXPO = TONAL_PARAMS.index("Exposure2012")
CONTRAST = TONAL_PARAMS.index("Contrast2012")


def emb(seed, base=None):
    rng = np.random.default_rng(seed)
    v = (base if base is not None else np.zeros(DIM)) \
        + rng.standard_normal(DIM) * 0.05
    return v / np.linalg.norm(v)


def sample(pid, expo, contrast, embedding):
    d = np.full(len(TONAL_PARAMS), np.nan)
    d[EXPO] = expo
    d[CONTRAST] = contrast
    return StyleSample(photo_id=pid, deltas=d, embedding=embedding,
                       process_version="15.4")


@pytest.fixture
def two_looks():
    """Look A: +1 EV, +20 contrast around axis a. Look B: −1 EV, −20."""
    a = np.zeros(DIM); a[0] = 1.0
    b = np.zeros(DIM); b[1] = 1.0
    samples = []
    for i in range(12):
        samples.append(sample(i, 1.0 + 0.05 * (i % 3), 20.0, emb(i, a)))
    for i in range(12, 24):
        samples.append(sample(i, -1.0 - 0.05 * (i % 3), -20.0, emb(i, b)))
    return samples


def test_families_are_discovered_not_assumed(two_looks):
    n = cluster_families(two_looks)
    assert n == 2
    fams = {s.family for s in two_looks[:12]}, {s.family for s in two_looks[12:]}
    assert fams[0] != fams[1] and len(fams[0]) == len(fams[1]) == 1
    med = family_median(two_looks, two_looks[0].family)
    assert med["Exposure2012"] == pytest.approx(1.05, abs=0.1)
    assert isinstance(family_traits(two_looks, 0), str)


def test_predict_blends_neighbors_and_clamps(two_looks):
    cluster_families(two_looks)
    a = np.zeros(DIM); a[0] = 1.0
    pred = predict(emb(99, a), two_looks, family=two_looks[0].family)
    assert not pred.abstained
    # Blend lands inside the family's observed range — never beyond (§6).
    assert 1.0 <= pred.params["Exposure2012"] <= 1.10
    assert pred.params["Contrast2012"] == pytest.approx(20.0)
    assert 0 < pred.confidence <= 1
    assert len(pred.neighbor_ids) > 0
    # NaN params (never set in this family) are absent, not zero.
    assert "Dehaze" not in pred.params


def test_abstains_on_dissimilar_photo(two_looks):
    cluster_families(two_looks)
    stranger = np.zeros(DIM); stranger[7] = 1.0  # orthogonal to both looks
    pred = predict(stranger, two_looks, family=two_looks[0].family)
    assert pred.abstained and pred.reason == "no_similar_history"
    assert pred.params == {}


def test_abstains_on_tiny_family():
    a = np.zeros(DIM); a[0] = 1.0
    samples = [sample(i, 1.0, 10.0, emb(i, a)) for i in range(2)]
    for s in samples:
        s.family = 0
    pred = predict(emb(9, a), samples, family=0)
    assert pred.abstained and pred.reason == "family_too_small"


def test_disagreeing_neighbors_lower_confidence(two_looks):
    cluster_families(two_looks)
    fam = two_looks[0].family
    a = np.zeros(DIM); a[0] = 1.0
    agreeing = predict(emb(99, a), two_looks, family=fam)
    # Same neighbors, but their exposure deltas now wildly disagree.
    for i, s in enumerate(m for m in two_looks if m.family == fam):
        s.deltas[EXPO] = (-1) ** i * 3.0
    disagreeing = predict(emb(99, a), two_looks, family=fam)
    assert disagreeing.confidence < agreeing.confidence
