import CoreImage
import Foundation
import ShootrKit
import Vision

/// shootr-analyze — CLI contract per design 03 §4.
///
///   probe    --files <list.json>               → JSONL metadata
///   analyze  --files <list.json> [--scale 0.5] → JSONL measurements
///   render   --file <raw> [--size 2048] --out <path>
///   version
///
/// File lists come via a JSON file, not argv (argv has length limits at 10k
/// scale). Errors are per-photo JSONL objects; exit code stays 0 unless the
/// invocation itself is malformed.

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write(Data((msg + "\n").utf8))
    exit(2)
}

func arg(_ name: String) -> String? {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: "--\(name)"), i + 1 < args.count
    else { return nil }
    return args[i + 1]
}

func loadFileList() -> [String] {
    guard let listPath = arg("files") else { fail("--files <list.json> required") }
    guard let data = FileManager.default.contents(atPath: listPath),
          let files = try? JSONDecoder().decode([String].self, from: data)
    else { fail("cannot read file list: \(listPath)") }
    return files
}

let command = CommandLine.arguments.dropFirst().first ?? "help"

switch command {
case "selftest":
    let failures = SelfTest.run()
    if failures.isEmpty {
        emitLine(["status": "ok"])
    } else {
        for f in failures { emitLine(ErrorOut(path: "selftest", error: f)) }
        exit(1)
    }

case "version":
    emitLine([
        "engine_version": engineVersion,
        "face_landmarks_revision": String(VNDetectFaceLandmarksRequestRevision3),
        "swift_helper": "shootr-analyze",
    ])

case "probe":
    for path in loadFileList() {
        autoreleasepool {
            let url = URL(fileURLWithPath: path)
            if let out = probe(url: url) {
                emitLine(out)
            } else {
                emitLine(ErrorOut(path: path, error: "probe_failed"))
            }
        }
    }

case "analyze":
    let scale = arg("scale").flatMap(Double.init) ?? 0.5
    for path in loadFileList() {
        // One autoreleasepool per image: without it CIImage/CVPixelBuffer
        // accumulate and a 64-image batch balloons past several GB
        // (design 03 §6).
        autoreleasepool {
            let url = URL(fileURLWithPath: path)
            do {
                emitLine(try analyze(url: url, scale: scale))
            } catch {
                emitLine(ErrorOut(path: path, error: String(describing: error)))
            }
        }
    }

case "render":
    guard let file = arg("file"), let out = arg("out")
    else { fail("render --file <raw> --out <path> [--size 2048] "
                + "[--crop x,y,w,h]") }
    let size = arg("size").flatMap(Double.init) ?? 2048
    do {
        // Display decode path — Apple defaults ON (design 03 §2).
        let decoded = try decode(url: URL(fileURLWithPath: file),
                                 path: .display, scale: 1.0)
        var image = decoded.image
        // Optional crop, normalized [x,y,w,h] with bottom-left origin —
        // the same convention as face bboxes, and CIImage's own extent
        // origin, so no flip. Serves the eye-band crops (design 11 §3).
        if let cropArg = arg("crop") {
            let parts = cropArg.split(separator: ",").compactMap {
                Double($0)
            }
            guard parts.count == 4 else { fail("--crop expects x,y,w,h") }
            let e = image.extent
            let rect = CGRect(
                x: e.origin.x + parts[0] * e.width,
                y: e.origin.y + parts[1] * e.height,
                width: parts[2] * e.width,
                height: parts[3] * e.height
            ).intersection(e)
            guard !rect.isEmpty else { fail("--crop outside image") }
            // Translate so the JPEG writer sees a zero-origin image.
            image = image.cropped(to: rect).transformed(
                by: CGAffineTransform(translationX: -rect.origin.x,
                                      y: -rect.origin.y))
        }
        let extent = image.extent
        let scale = min(1.0, size / max(extent.width, extent.height))
        let scaled = image.transformed(
            by: CGAffineTransform(scaleX: scale, y: scale))
        let color = CGColorSpace(name: CGColorSpace.sRGB)!
        try sharedContext.writeJPEGRepresentation(
            of: scaled, to: URL(fileURLWithPath: out),
            colorSpace: color, options: [:])
        emitLine(["path": file, "out": out, "status": "ok"])
    } catch {
        emitLine(ErrorOut(path: file, error: String(describing: error)))
        exit(1)
    }

default:
    fail("""
    usage: shootr-analyze <command>
      probe    --files <list.json>
      analyze  --files <list.json> [--scale 0.5]
      render   --file <raw> [--size 2048] --out <path>
      version
    """)
}
