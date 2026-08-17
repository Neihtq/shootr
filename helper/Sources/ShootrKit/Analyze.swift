import CoreImage
import Foundation
import Vision

/// Full analysis of one photo (design 03 §4–5). All Vision requests batch
/// into ONE VNImageRequestHandler per image — one decode, one pixel buffer.
public func analyze(url: URL, scale: Double) throws -> AnalyzeOut {
    var timing: [String: Int] = [:]
    let t0 = Date()

    // Measurement decode: enhancement OFF (design 03 §2).
    let decoded = try decode(url: url, path: .measurement, scale: scale)
    timing["decode"] = ms(since: t0)

    // --- Vision pass -------------------------------------------------------
    let tVision = Date()
    let faceRects = VNDetectFaceLandmarksRequest()
    faceRects.revision = VNDetectFaceLandmarksRequestRevision3
    let quality = VNDetectFaceCaptureQualityRequest()
    let saliency = VNGenerateAttentionBasedSaliencyImageRequest()
    let horizon = VNDetectHorizonRequest()
    let featurePrint = VNGenerateImageFeaturePrintRequest()

    let handler = VNImageRequestHandler(ciImage: decoded.image)
    try? handler.perform([faceRects, quality, saliency, horizon, featurePrint])
    timing["vision"] = ms(since: tVision)

    // --- Frame sharpness ---------------------------------------------------
    let tSharp = Date()
    var frame = FrameOut(
        sharpnessTiles: [], sharpnessMax: 0, sharpnessMean: 0,
        clippedHi: nil, clippedLo: nil, horizonAngle: nil, exposureBias: nil)
    if let lum = renderLuminance(decoded.image) {
        let map = Sharpness.tileMap(
            pixels: lum.pixels, width: lum.width, height: lum.height)
        frame.sharpnessTiles = map.tiles
        frame.sharpnessMax = map.max
        frame.sharpnessMean = map.mean
        let clip = clipping(pixels: lum.pixels)
        frame.clippedHi = clip.hi
        frame.clippedLo = clip.lo
    }
    if let h = horizon.results?.first {
        frame.horizonAngle = Double(h.angle) * 180 / .pi
    }
    timing["sharpness"] = ms(since: tSharp)

    // --- Faces + eyes ------------------------------------------------------
    let tEyes = Date()
    var faces: [FaceOut] = []
    let qualityByBox = (quality.results ?? []).map {
        ($0.boundingBox, $0.faceCaptureQuality)
    }
    for (i, obs) in (faceRects.results ?? []).enumerated() {
        faces.append(analyzeFace(
            obs, idx: i, url: url, frameMax: frame.sharpnessMax,
            qualityByBox: qualityByBox))
    }
    timing["eyes"] = ms(since: tEyes)

    var saliencyOut: SaliencyOut?
    if let s = saliency.results?.first, let obj = s.salientObjects?.first {
        saliencyOut = SaliencyOut(attentionBbox: rect(obj.boundingBox))
    }

    var embedding: String?
    var embeddingDim: Int?
    if let fp = featurePrint.results?.first as? VNFeaturePrintObservation {
        embedding = fp.data.base64EncodedString()
        embeddingDim = fp.elementCount
    }

    return AnalyzeOut(
        path: url.path,
        decodeMode: decoded.mode,
        engineVersion: engineVersion,
        frame: frame,
        saliency: saliencyOut,
        faces: faces,
        embedding: embedding,
        embeddingDim: embeddingDim,
        timingMs: timing)
}

/// Per-face: landmarks → eye crops, EAR blink baseline, and the two-tier eye
/// sharpness pass — eye ROIs re-decoded at FULL scale so we pay full-res
/// cost on ~0.1% of the pixels (design 03 §5).
private func analyzeFace(
    _ obs: VNFaceObservation, idx: Int, url: URL, frameMax: Double,
    qualityByBox: [(CGRect, Float?)]
) -> FaceOut {
    var eyes: [String: EyeOut] = [:]

    let pairs: [(String, VNFaceLandmarkRegion2D?)] = [
        ("l", obs.landmarks?.leftEye), ("r", obs.landmarks?.rightEye),
    ]
    for (side, region) in pairs {
        guard let region else {
            eyes[side] = EyeOut(sharpNorm: nil, open: nil)
            continue
        }
        let imagePoints = region.pointsInImage(
            imageSize: CGSize(width: 4096, height: 4096))
        let open = Blink.openness(points: imagePoints)
        let sharp = eyeSharpness(
            url: url, face: obs, eyePoints: region.normalizedPoints,
            frameMax: frameMax)
        eyes[side] = EyeOut(sharpNorm: sharp, open: open)
    }

    // Match capture quality by bbox overlap (separate request, same faces).
    let q = qualityByBox.first {
        $0.0.intersection(obs.boundingBox).width > 0
    }?.1

    return FaceOut(
        idx: idx,
        bbox: rect(obs.boundingBox),
        roll: obs.roll?.doubleValue,
        yaw: obs.yaw?.doubleValue,
        pitch: obs.pitch?.doubleValue,
        captureQuality: q.map(Double.init),
        eyes: eyes,
        eyeSource: "ear_landmarks",
        faceprint: nil)  // populated when identity clustering lands end-to-end
}

/// Tier 2 of the two-tier approach: full-scale decode cropped to the eye ROI,
/// normalized against the sharpest frame tile (design 03 §3.1).
private func eyeSharpness(
    url: URL, face: VNFaceObservation, eyePoints: [CGPoint], frameMax: Double
) -> Double? {
    guard frameMax > 0, !eyePoints.isEmpty,
          let full = try? decode(url: url, path: .measurement, scale: 1.0)
    else { return nil }

    let extent = full.image.extent
    // Eye points are normalized within the face bbox; map to image space.
    let fb = face.boundingBox
    let xs = eyePoints.map { fb.origin.x + $0.x * fb.width }
    let ys = eyePoints.map { fb.origin.y + $0.y * fb.height }
    guard let minX = xs.min(), let maxX = xs.max(),
          let minY = ys.min(), let maxY = ys.max() else { return nil }

    // Pad the tight landmark box by 50% each side for gradient context.
    let w = (maxX - minX) * extent.width, h = (maxY - minY) * extent.height
    let crop = CGRect(
        x: minX * extent.width - w * 0.5,
        y: minY * extent.height - h * 0.5,
        width: w * 2, height: h * 2
    ).intersection(extent)
    guard !crop.isEmpty, crop.width > 8, crop.height > 8,
          let lum = renderLuminance(full.image, rect: crop) else { return nil }

    let eyeEnergy = Sharpness.tenengrad(
        pixels: lum.pixels, width: lum.width, height: lum.height)
    return min(1.5, eyeEnergy / frameMax)  // >1 = eye sharper than any tile
}

private func clipping(pixels: [UInt8]) -> (hi: Double, lo: Double) {
    var hi = 0, lo = 0
    for p in pixels {
        if p >= 254 { hi += 1 } else if p <= 1 { lo += 1 }
    }
    let n = Double(pixels.count)
    return (Double(hi) / n, Double(lo) / n)
}

private func rect(_ r: CGRect) -> [Double] {
    [r.origin.x, r.origin.y, r.width, r.height].map(Double.init)
}

private func ms(since: Date) -> Int {
    Int(Date().timeIntervalSince(since) * 1000)
}
