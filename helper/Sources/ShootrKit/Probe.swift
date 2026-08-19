import Foundation
import ImageIO

/// EXIF probe — no pixel decode (design 02 §2 stage 4). ImageIO handles all
/// 893 RAW models the same way the decoder does, so probe and decode never
/// disagree about a file.
public struct ProbeOut: Codable {
    public var path: String
    public var capturedAt: String?
    public var subsec: Int?
    public var cameraModel: String?
    public var lensModel: String?
    public var iso: Int?
    public var shutter: Double?
    public var aperture: Double?
    public var focalLength: Double?
    public var exposureBias: Double?
    public var orientation: Int?
    public var width: Int?
    public var height: Int?

    enum CodingKeys: String, CodingKey {
        case path
        case capturedAt = "captured_at"
        case subsec
        case cameraModel = "camera_model"
        case lensModel = "lens_model"
        case iso, shutter, aperture
        case focalLength = "focal_length"
        case exposureBias = "exposure_bias"
        case orientation, width, height
    }
}

public func probe(url: URL) -> ProbeOut? {
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil)
            as? [CFString: Any] else {
        return nil
    }
    let exif = props[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
    let tiff = props[kCGImagePropertyTIFFDictionary] as? [CFString: Any] ?? [:]

    var out = ProbeOut(path: url.path)
    if let dt = exif[kCGImagePropertyExifDateTimeOriginal] as? String {
        out.capturedAt = normalizeExifDate(dt)
    }
    // SubSecTimeOriginal disambiguates burst frames sharing a whole-second
    // timestamp (design 02 §2 stage 4).
    if let ss = exif[kCGImagePropertyExifSubsecTimeOriginal] as? String {
        out.subsec = Int(ss.prefix(3).padding(toLength: 3, withPad: "0",
                                              startingAt: 0))
    }
    out.cameraModel = tiff[kCGImagePropertyTIFFModel] as? String
    out.lensModel = exif[kCGImagePropertyExifLensModel] as? String
    // ISO lives under different keys per vendor: Canon CR3 leaves
    // ISOSpeedRatings empty and fills ISOSpeed / RecommendedExposureIndex
    // (verified against real CR3s), while JPEG/other RAWs use the
    // ISOSpeedRatings array. Try each in turn rather than assuming one.
    out.iso = (exif[kCGImagePropertyExifISOSpeedRatings] as? [Any])?
        .first.flatMap { ($0 as? NSNumber)?.intValue }
        ?? (exif[kCGImagePropertyExifISOSpeed] as? NSNumber)?.intValue
        ?? (exif[kCGImagePropertyExifRecommendedExposureIndex]
            as? NSNumber)?.intValue
    out.shutter = exif[kCGImagePropertyExifExposureTime] as? Double
    out.aperture = exif[kCGImagePropertyExifFNumber] as? Double
    out.focalLength = exif[kCGImagePropertyExifFocalLength] as? Double
    out.exposureBias = exif[kCGImagePropertyExifExposureBiasValue] as? Double
    out.orientation = props[kCGImagePropertyOrientation] as? Int
    out.width = props[kCGImagePropertyPixelWidth] as? Int
    out.height = props[kCGImagePropertyPixelHeight] as? Int
    return out
}

/// EXIF "2026:06:14 15:22:08" → ISO-8601 "2026-06-14T15:22:08".
func normalizeExifDate(_ raw: String) -> String {
    let parts = raw.split(separator: " ", maxSplits: 1)
    guard parts.count == 2 else { return raw }
    return parts[0].replacingOccurrences(of: ":", with: "-") + "T" + parts[1]
}
