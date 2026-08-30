# Sharpness comparability reproducer

`DSCF0202-X-E5-render.jpg` — display-path render of the Fujifilm X-E5 sample
(CC0, raw.pixls.us `FUJIFILM/X-E5/DSCF0202.RAF`). Visibly sharp: building
edges, window mullions, roof tiles all crisp.

Measured `sharpness_max = 0.00065` → below `MIN_FRAME_SHARPNESS_FOR_EYE_FOCUS`
(0.005) → scored `sharpness = 0.0` with `diagnosis: motion_blur_or_shake`.

Reproduce (the RAF is not committed — 83 MB, and it is a fetchable CC0 file):

```bash
curl -LO https://raw.pixls.us/data/FUJIFILM/X-E5/DSCF0202.RAF
.venv/bin/python engine/tools/sharpness_norm_probe.py \
    --cross <dir with the RAF> --shoot "<a Canon shoot dir>"
```

Full analysis: `../2026-08-30-arw-raf-validation.md` §4.
