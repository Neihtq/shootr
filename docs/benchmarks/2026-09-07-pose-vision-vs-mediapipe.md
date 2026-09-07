# Pose on both analyzers — neither dominates, and the cutover changes character

The Swift path emits Vision body pose; without a counterpart the analyzer
cutover would silently lose pose grouping (05 §4) and the limb-cut flag
(04 §2.4). `analyzer/shootr_analyzer/pose.py` closes that with MediaPipe Pose
(heavy), renaming its landmarks onto Vision's joint names so `shootr.pose`
consumes either analyzer unchanged.

## Measured on 16 real event frames

| | Vision | MediaPipe (heavy) |
|---|---|---|
| bodies detected | **35** | 18 |
| photos yielding a usable pose vector | 10 | **15** |

The two fail in opposite directions, which is why one number would have been
misleading:

- **Vision detects roughly twice as many bodies** — better multi-person
  recall. On one dark 7-person reception frame Vision found 7 bodies and
  MediaPipe found **0**.
- **MediaPipe yields more usable vectors** because it returns *complete*
  skeletons (it infers occluded joints), while many of Vision's extra
  detections lack hips or shoulders and correctly abstain.

Consequence for the cutover, stated plainly: pose is **not lost**, but its
character changes — pose *grouping* may improve while limb-cut coverage drops
on crowded frames. This strengthens the design-13 §2.1 case for ViTPose-L
(multi-person *and* complete skeletons) rather than treating MediaPipe as a
sufficient endpoint. It is registered as tier `floor` accordingly.

## A correctness fix this comparison forced

MediaPipe extrapolates occluded limbs **past the frame bounds**: 35 of 182
joints (19%) came back outside [0,1], e.g. a knee at y = −0.165. Those
guesses arrive with low confidence (0.02–0.17), so the engine's 0.3 filter
happened to drop them — but relying on that coincidence is fragile, and a
confidently-guessed out-of-frame joint would have produced a **false
limb-cut flag**.

`limb_cut_at_joint` now requires the joint to be *inside* the frame as well
as near an edge. That is also the semantically correct rule for either
analyzer: a joint positioned outside the frame means the limb left frame
somewhere before it, which is exactly the "cut between joints" case 04 §2.4
calls normal framing.
