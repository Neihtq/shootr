import Foundation

/// Tenengrad (Sobel gradient energy) over Laplacian variance: less
/// noise-sensitive, which matters at the ISO 3200–12800 that indoor wedding
/// work lives at (design 03 §3.2). Pure math — fully unit-testable.
public enum Sharpness {

    /// Mean squared Sobel gradient magnitude over the buffer, normalized so
    /// values are comparable across crops. Absolute numbers are meaningless;
    /// only ratios are diagnostic (design 03 §3.1).
    public static func tenengrad(
        pixels: [UInt8], width: Int, height: Int
    ) -> Double {
        guard width > 2, height > 2 else { return 0 }
        var sum = 0.0
        for y in 1..<(height - 1) {
            let up = (y - 1) * width, mid = y * width, dn = (y + 1) * width
            for x in 1..<(width - 1) {
                let a = Double(pixels[up + x - 1]), b = Double(pixels[up + x])
                let c = Double(pixels[up + x + 1])
                let d = Double(pixels[mid + x - 1]), f = Double(pixels[mid + x + 1])
                let g = Double(pixels[dn + x - 1]), h = Double(pixels[dn + x])
                let i = Double(pixels[dn + x + 1])
                let gx = (c + 2 * f + i) - (a + 2 * d + g)
                let gy = (g + 2 * h + i) - (a + 2 * b + c)
                sum += gx * gx + gy * gy
            }
        }
        let n = Double((width - 2) * (height - 2))
        // Max |g| per axis is 4*255; normalize energy into a sane 0..1-ish range.
        return sum / n / (4.0 * 255 * 255)
    }

    public struct TileMap: Codable {
        public let tiles: [[Double]]  // 16×16, row-major
        public let max: Double
        public let mean: Double
    }

    /// 16×16 tile grid (design 03 §3.3): normalization denominator,
    /// landscape focus-plane detection, motion-blur detection.
    public static func tileMap(
        pixels: [UInt8], width: Int, height: Int, grid: Int = 16
    ) -> TileMap {
        var tiles = [[Double]](
            repeating: [Double](repeating: 0, count: grid), count: grid)
        var maxV = 0.0, sum = 0.0
        let tw = width / grid, th = height / grid
        guard tw > 2, th > 2 else {
            return TileMap(tiles: tiles, max: 0, mean: 0)
        }
        for ty in 0..<grid {
            for tx in 0..<grid {
                var tile = [UInt8](repeating: 0, count: tw * th)
                let ox = tx * tw, oy = ty * th
                for row in 0..<th {
                    let src = (oy + row) * width + ox
                    tile.replaceSubrange(
                        row * tw..<(row + 1) * tw,
                        with: pixels[src..<src + tw])
                }
                let v = tenengrad(pixels: tile, width: tw, height: th)
                tiles[ty][tx] = v
                maxV = Swift.max(maxV, v)
                sum += v
            }
        }
        return TileMap(
            tiles: tiles, max: maxV, mean: sum / Double(grid * grid))
    }
}
