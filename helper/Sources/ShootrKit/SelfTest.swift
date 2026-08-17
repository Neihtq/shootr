import CoreGraphics
import Foundation

/// Unit checks for the pure-math components, runnable as
/// `shootr-analyze selftest`. Exists because no test framework ships with
/// CLI-tools-only (no Xcode, SPEC §1); pytest drives this and asserts exit 0.
public enum SelfTest {

    public static func run() -> [String] {
        var failures: [String] = []
        func check(_ cond: Bool, _ name: String) {
            if !cond { failures.append(name) }
        }

        // --- Tenengrad ------------------------------------------------------
        let flat = [UInt8](repeating: 128, count: 64 * 64)
        check(Sharpness.tenengrad(pixels: flat, width: 64, height: 64) == 0,
              "flat field has zero gradient energy")

        let w = 64, h = 64
        var edge = [UInt8](repeating: 0, count: w * h)
        var ramp = [UInt8](repeating: 0, count: w * h)
        var fine = [UInt8](repeating: 0, count: w * h)
        var coarse = [UInt8](repeating: 0, count: w * h)
        for y in 0..<h {
            for x in 0..<w {
                edge[y * w + x] = x < w / 2 ? 0 : 255
                ramp[y * w + x] = UInt8(x * 255 / (w - 1))
                // Period-4 pattern: a 1-px checkerboard aliases to ZERO under
                // Sobel (x-1 and x+1 share parity, gradients cancel).
                fine[y * w + x] = ((x / 2) + (y / 2)) % 2 == 0 ? 0 : 255
                coarse[y * w + x] = ((x / 16) + (y / 16)) % 2 == 0 ? 0 : 255
            }
        }
        // The orderings every sharpness comparison depends on.
        check(Sharpness.tenengrad(pixels: edge, width: w, height: h)
              > Sharpness.tenengrad(pixels: ramp, width: w, height: h) * 2,
              "hard edge beats soft ramp")
        check(Sharpness.tenengrad(pixels: fine, width: w, height: h)
              > Sharpness.tenengrad(pixels: coarse, width: w, height: h),
              "fine detail beats coarse")
        check(Sharpness.tenengrad(pixels: [1, 2], width: 2, height: 1) == 0,
              "degenerate size returns zero")

        // --- Tile map -------------------------------------------------------
        // Sharp detail confined to one quadrant: the shallow-DoF signature
        // the scorer depends on (design 04 §2.3).
        let W = 256, H = 256
        var px = [UInt8](repeating: 128, count: W * H)
        for y in 0..<(H / 4) {
            for x in 0..<(W / 4) {
                px[y * W + x] = ((x / 2) + (y / 2)) % 2 == 0 ? 0 : 255
            }
        }
        let map = Sharpness.tileMap(pixels: px, width: W, height: H)
        check(map.max > 0, "sharp quadrant produces nonzero max")
        check(map.mean < map.max / 4, "mean well below max for local sharpness")
        var sharpOutsideQuadrant = false
        for ty in 0..<16 {
            for tx in 0..<16
            where map.tiles[ty][tx] > map.max / 2 && (tx >= 4 || ty >= 4) {
                sharpOutsideQuadrant = true
            }
        }
        check(!sharpOutsideQuadrant, "sharp tiles localized to quadrant")

        let soft = [UInt8](repeating: 100, count: W * H)
        let softMap = Sharpness.tileMap(pixels: soft, width: W, height: H)
        check(softMap.max == 0 && softMap.mean == 0,
              "uniformly flat map = motion-blur signature")

        // --- Blink EAR ------------------------------------------------------
        func contour(_ height: Double) -> [CGPoint] {
            [CGPoint(x: 0, y: 5), CGPoint(x: 10, y: 5 + height / 2),
             CGPoint(x: 20, y: 5 + height / 2), CGPoint(x: 30, y: 5),
             CGPoint(x: 20, y: 5 - height / 2), CGPoint(x: 10, y: 5 - height / 2)]
        }
        check((Blink.openness(points: contour(10)) ?? 0) > 0.9,
              "open eye near 1")
        check((Blink.openness(points: contour(2)) ?? 1) < 0.1,
              "closed eye near 0")
        if let p = Blink.openness(points: contour(6)) {
            check(p > 0.2 && p < 0.8, "partial blink in between")
        } else {
            failures.append("partial blink returned nil")
        }
        check(Blink.openness(points: []) == nil, "empty contour abstains")
        let vertical = [CGPoint(x: 5, y: 0), CGPoint(x: 5, y: 1),
                        CGPoint(x: 5, y: 2), CGPoint(x: 5, y: 3)]
        check(Blink.openness(points: vertical) == nil,
              "zero-width contour abstains, no divide by zero")

        // --- Probe date -----------------------------------------------------
        check(normalizeExifDate("2026:06:14 15:22:08") == "2026-06-14T15:22:08",
              "EXIF date normalized to ISO-8601")
        check(normalizeExifDate("garbage") == "garbage",
              "malformed date passed through")

        return failures
    }
}
