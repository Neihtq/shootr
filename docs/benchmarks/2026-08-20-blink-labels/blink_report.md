# Blink validation — hand labels vs both detectors

43 faces · 33 labelled open/closed · 10 unclear (excluded)

## EAR (Swift landmarks)
- coverage: 29/33 labelled faces have a value
- score distribution: open μ=0.85 (n=23), closed μ=0.31 (n=6)
- best threshold **0.42**: balanced acc 89.5%, false-reject 4.3%, false-accept 16.7%
- at culling's current 0.4: balanced acc 81.2%, **false-reject 4.3%** (open eyes flagged closed — the asymmetric failure)

## blendshapes (MediaPipe)
- coverage: 27/33 labelled faces have a value
- score distribution: open μ=0.81 (n=21), closed μ=0.47 (n=6)
- best threshold **0.60**: balanced acc 92.9%, false-reject 14.3%, false-accept 0.0%
- at culling's current 0.4: balanced acc 64.3%, **false-reject 4.8%** (open eyes flagged closed — the asymmetric failure)

_False-reject is the number that matters: it is the rate at which good photos would be rejected with the stated reason 'eyes closed'. Whichever source wins, culling's threshold should move to that source's best value (design 06 §6)._
