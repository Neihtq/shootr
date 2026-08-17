import Foundation

/// JSONL output shapes (design 03 §4). One object per photo, flushed per
/// photo. Errors are per-photo objects, never a nonzero exit — one corrupt
/// RAW must not fail the batch.

public struct EyeOut: Codable {
    public var sharpNorm: Double?
    public var open: Double?
    enum CodingKeys: String, CodingKey {
        case sharpNorm = "sharp_norm", open
    }
    public init(sharpNorm: Double?, open: Double?) {
        self.sharpNorm = sharpNorm
        self.open = open
    }
}

public struct FaceOut: Codable {
    public var idx: Int
    public var bbox: [Double]  // normalized [x, y, w, h]
    public var roll: Double?
    public var yaw: Double?
    public var pitch: Double?
    public var captureQuality: Double?
    public var eyes: [String: EyeOut]  // "l" / "r"
    public var eyeSource: String
    public var faceprint: String?  // base64

    enum CodingKeys: String, CodingKey {
        case idx, bbox, roll, yaw, pitch
        case captureQuality = "capture_quality"
        case eyes
        case eyeSource = "eye_source"
        case faceprint
    }
    public init(idx: Int, bbox: [Double], roll: Double?, yaw: Double?,
                pitch: Double?, captureQuality: Double?,
                eyes: [String: EyeOut], eyeSource: String, faceprint: String?) {
        self.idx = idx; self.bbox = bbox; self.roll = roll; self.yaw = yaw
        self.pitch = pitch; self.captureQuality = captureQuality
        self.eyes = eyes; self.eyeSource = eyeSource; self.faceprint = faceprint
    }
}

public struct FrameOut: Codable {
    public var sharpnessTiles: [[Double]]
    public var sharpnessMax: Double
    public var sharpnessMean: Double
    public var clippedHi: Double?
    public var clippedLo: Double?
    public var horizonAngle: Double?
    public var exposureBias: Double?

    enum CodingKeys: String, CodingKey {
        case sharpnessTiles = "sharpness_tiles"
        case sharpnessMax = "sharpness_max"
        case sharpnessMean = "sharpness_mean"
        case clippedHi = "clipped_hi"
        case clippedLo = "clipped_lo"
        case horizonAngle = "horizon_angle"
        case exposureBias = "exposure_bias"
    }
    public init(sharpnessTiles: [[Double]], sharpnessMax: Double,
                sharpnessMean: Double, clippedHi: Double?, clippedLo: Double?,
                horizonAngle: Double?, exposureBias: Double?) {
        self.sharpnessTiles = sharpnessTiles
        self.sharpnessMax = sharpnessMax
        self.sharpnessMean = sharpnessMean
        self.clippedHi = clippedHi; self.clippedLo = clippedLo
        self.horizonAngle = horizonAngle; self.exposureBias = exposureBias
    }
}

public struct SaliencyOut: Codable {
    public var attentionBbox: [Double]?
    enum CodingKeys: String, CodingKey {
        case attentionBbox = "attention_bbox"
    }
    public init(attentionBbox: [Double]?) { self.attentionBbox = attentionBbox }
}

public struct AnalyzeOut: Codable {
    public var path: String
    public var decodeMode: String
    public var engineVersion: String
    public var frame: FrameOut
    public var saliency: SaliencyOut?
    public var faces: [FaceOut]
    public var embedding: String?  // base64 float32 feature print
    public var embeddingDim: Int?
    public var timingMs: [String: Int]

    enum CodingKeys: String, CodingKey {
        case path
        case decodeMode = "decode_mode"
        case engineVersion = "engine_version"
        case frame, saliency, faces, embedding
        case embeddingDim = "embedding_dim"
        case timingMs = "timing_ms"
    }
    public init(path: String, decodeMode: String, engineVersion: String,
                frame: FrameOut, saliency: SaliencyOut?, faces: [FaceOut],
                embedding: String?, embeddingDim: Int?, timingMs: [String: Int]) {
        self.path = path; self.decodeMode = decodeMode
        self.engineVersion = engineVersion; self.frame = frame
        self.saliency = saliency; self.faces = faces
        self.embedding = embedding; self.embeddingDim = embeddingDim
        self.timingMs = timingMs
    }
}

public struct ErrorOut: Codable {
    public var path: String
    public var error: String
    public init(path: String, error: String) {
        self.path = path; self.error = error
    }
}

public let engineVersion = "0.1.0+vision3"

private let encoder: JSONEncoder = {
    let e = JSONEncoder()
    e.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
    return e
}()

/// Emit one JSONL line and flush immediately — a batch that dies at photo
/// 400 of 500 keeps 400 results (design 03 §4).
public func emitLine<T: Encodable>(_ value: T) {
    guard let data = try? encoder.encode(value) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0A]))
}
