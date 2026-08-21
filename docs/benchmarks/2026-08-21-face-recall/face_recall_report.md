# Face-recall check — disputed detections, human-judged

## SCRFD-only (python's extra faces)
- 21 disputed: 8 real, 13 not faces, 0 unclear, 0 unlabelled
- **precision of the extras: 38%**

## Vision-only (swift's extra faces)
- 0 disputed: 0 real, 0 not faces, 0 unclear, 0 unlabelled

_Extras that are REAL faces = recall the other detector missed (good). Extras that are NOT faces = phantom subjects feeding blink/quality metrics (bad). This decides whether SCRFD's 77-vs-56 count is an edge or a liability (design 13 §4)._
