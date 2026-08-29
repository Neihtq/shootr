# Blink validation — hand labels vs both detectors

273 faces · 252 labelled open/closed · 21 unclear (excluded)

## EAR (Swift landmarks)
- coverage: 233/252 labelled faces have a value
- score distribution: open μ=0.32 (n=230), closed μ=0.11 (n=3)
- best threshold **0.24**: balanced acc 85.9%, false-reject 28.3%, false-accept 0.0%
- at culling's current 0.4: balanced acc 62.0%, **false-reject 76.1%** (open eyes flagged closed — the asymmetric failure)

## blendshapes (MediaPipe)
- coverage: 250/252 labelled faces have a value
- score distribution: open μ=0.77 (n=247), closed μ=0.69 (n=3)
- best threshold **0.66**: balanced acc 78.3%, false-reject 10.1%, false-accept 33.3%
- at culling's current 0.4: balanced acc 50.0%, **false-reject 0.0%** (open eyes flagged closed — the asymmetric failure)

_False-reject is the number that matters: it is the rate at which good photos would be rejected with the stated reason 'eyes closed'. Whichever source wins, culling's threshold should move to that source's best value (design 06 §6)._
