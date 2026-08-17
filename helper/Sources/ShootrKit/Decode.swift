import CoreImage
import Foundation

/// The two decode paths (design 03 §2). Mixing them is a silent-wrongness
/// bug: scores would drift with Apple's decoder version.
public enum DecodePath {
    /// All enhancement OFF. Measuring a default decode measures Apple's
    /// sharpening kernel, not whether the subject was in focus.
    case measurement
    /// Apple defaults ON — previews for the UI, style-learning features.
    case display
}

public enum DecodeError: Error, CustomStringConvertible {
    case unreadable(String)
    public var description: String {
        switch self {
        case .unreadable(let p): return "cannot decode: \(p)"
        }
    }
}

public struct Decoded {
    public let image: CIImage
    public let mode: String  // "scaled" | "full" | "jpeg"
}

/// One CIContext per process — per-image contexts recompile Metal shaders
/// (design 03 §6).
public let sharedContext = CIContext(options: [.cacheIntermediates: false])

public func decode(url: URL, path: DecodePath, scale: Double) throws -> Decoded {
    if let raw = CIRAWFilter(imageURL: url) {
        raw.scaleFactor = Float(scale)  // decode small, don't downsample
        switch path {
        case .measurement:
            // THE critical correctness rule (design 03 §2).
            raw.sharpnessAmount = 0
            raw.detailAmount = 0
            raw.luminanceNoiseReductionAmount = 0
            raw.colorNoiseReductionAmount = 0
            raw.moireReductionAmount = 0
            raw.boostAmount = 0
            raw.isGamutMappingEnabled = false
            raw.isLensCorrectionEnabled = false  // geometry must not shift
        case .display:
            break  // Apple defaults on
        }
        guard let img = raw.outputImage else {
            throw DecodeError.unreadable(url.path)
        }
        return Decoded(image: img, mode: scale >= 1.0 ? "full" : "scaled")
    }
    // Non-RAW (JPEG/HEIC/TIFF): no decoder enhancement to disable.
    guard var img = CIImage(contentsOf: url) else {
        throw DecodeError.unreadable(url.path)
    }
    if scale < 1.0 {
        img = img.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
    }
    return Decoded(image: img, mode: "jpeg")
}

/// Render a CIImage region to an 8-bit grayscale buffer for gradient math.
public func renderLuminance(_ image: CIImage, rect: CGRect? = nil)
    -> (pixels: [UInt8], width: Int, height: Int)? {
    let bounds = (rect ?? image.extent).integral
    let w = Int(bounds.width), h = Int(bounds.height)
    guard w > 1, h > 1, w * h < 64_000_000 else { return nil }
    var buf = [UInt8](repeating: 0, count: w * h)
    sharedContext.render(
        image, toBitmap: &buf, rowBytes: w, bounds: bounds,
        format: .L8, colorSpace: CGColorSpaceCreateDeviceGray())
    return (buf, w, h)
}
