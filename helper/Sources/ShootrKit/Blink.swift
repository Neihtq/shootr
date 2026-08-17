import CoreGraphics
import Foundation

/// Landmark eye-aspect-ratio blink baseline (design 03 §5 option 1).
/// Ships in the helper with `eye_source` provenance; the MediaPipe refiner
/// (option 2) replaces it Python-side. Known unreliable on squints and
/// extreme yaw — the scorer abstains on yaw, and this must pass validation
/// against hand-labelled frames before it drives culling.
public enum Blink {

    /// Eye aspect ratio from an eye contour: polygon height / width.
    public static func aspectRatio(points: [CGPoint]) -> Double? {
        guard points.count >= 4 else { return nil }
        let xs = points.map(\.x), ys = points.map(\.y)
        let w = xs.max()! - xs.min()!
        guard w > 0 else { return nil }
        return Double((ys.max()! - ys.min()!) / w)
    }

    // Typical EAR: ~0.10 fully closed, ~0.30+ fully open. Calibration
    // targets, refined by the benchmark's hand-labelled frames.
    static let closedEAR = 0.10
    static let openEAR = 0.30

    /// Map EAR to a 0..1 open estimate.
    public static func openness(points: [CGPoint]) -> Double? {
        guard let ear = aspectRatio(points: points) else { return nil }
        let t = (ear - closedEAR) / (openEAR - closedEAR)
        return min(1.0, max(0.0, t))
    }
}
