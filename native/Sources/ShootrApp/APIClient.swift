import Foundation

/// Codable mirrors of the engine payloads (design 10 §3, 12 §2).
///
/// Contract rule 1 applies with full force here: this client NEVER computes
/// domain values. A second, subtly different scoring implementation in Swift
/// would produce scores that disagree with the web client — exactly the
/// divergence the API seam exists to prevent (design 12 §2).
///
/// `value: Double?` nil is semantically load-bearing: not-applicable or
/// detector-abstained renders as "—", never as a zero bar (design 10 §3).

struct ScoreComponent: Codable {
    let value: Double?
    let weight: Double
    let contrib: Double?
}

struct Score: Codable {
    let profile: String
    let total: Double
    let components: [String: ScoreComponent]
    let flags: [String]
}

struct EyeInfo: Codable {
    let sharpNorm: Double?
    let open: Double?
    enum CodingKeys: String, CodingKey {
        case sharpNorm = "sharp_norm", open
    }
}

struct FaceInfo: Codable {
    let idx: Int
    let bbox: [Double]
    let eyes: [String: EyeInfo]  // "left" / "right"
}

struct SelectionInfo: Codable {
    let state: String
    let rank: Int?
    let reason: String
    let userOverride: Bool
    enum CodingKeys: String, CodingKey {
        case state, rank, reason
        case userOverride = "user_override"
    }
}

struct PhotoDetail: Codable {
    let id: Int
    let filename: String
    let relPath: String?
    let missing: Bool
    let faces: [FaceInfo]
    let score: Score?
    let selection: SelectionInfo?
    // EXIF (probed at ingest; design 02 §2 stage 4)
    let cameraModel: String?
    let lensModel: String?
    let iso: Int?
    let shutter: Double?
    let aperture: Double?
    let focalLength: Double?
    let exposureBias: Double?
    let capturedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, filename, missing, faces, score, selection
        case relPath = "rel_path"
        case cameraModel = "camera_model"
        case lensModel = "lens_model"
        case iso, shutter, aperture
        case focalLength = "focal_length"
        case exposureBias = "exposure_bias"
        case capturedAt = "captured_at"
    }

    /// "1/250s · f/1.8 · ISO 800 · 85mm · +0.3 EV" — the photographer's
    /// shorthand. Only present fields appear.
    var exifLine: String {
        var parts: [String] = []
        if let s = shutter {
            parts.append(s >= 1 ? String(format: "%.1fs", s)
                : "1/\(Int((1 / s).rounded()))s")
        }
        if let a = aperture { parts.append(String(format: "f/%.1f", a)) }
        if let i = iso { parts.append("ISO \(i)") }
        if let f = focalLength { parts.append("\(Int(f.rounded()))mm") }
        if let b = exposureBias, b != 0 {
            parts.append(String(format: "%+.1f EV", b))
        }
        return parts.joined(separator: " · ")
    }
}

struct Shoot: Codable, Identifiable {
    let id: Int
    let name: String
    let profile: String
    let photoCount: Int
    let latestSelectionId: Int?
    enum CodingKeys: String, CodingKey {
        case id, name, profile
        case photoCount = "photo_count"
        case latestSelectionId = "latest_selection_id"
    }
}

struct PhotoGroup: Codable, Identifiable {
    let id: Int
    let isBracket: Bool
    let photoIds: [Int]
    enum CodingKeys: String, CodingKey {
        case id
        case isBracket = "is_bracket"
        case photoIds = "photo_ids"
    }
}

struct SelectionEntry: Codable {
    let photoId: Int
    let state: String
    let rank: Int?
    let reason: String
    let userOverride: Int
    enum CodingKeys: String, CodingKey {
        case state, rank, reason
        case photoId = "photo_id"
        case userOverride = "user_override"
    }
}

struct Selection: Codable {
    let id: Int
    let entries: [SelectionEntry]
}

struct Library: Codable {
    let id: Int
    let rootPath: String
    let online: Bool
    enum CodingKeys: String, CodingKey {
        case id, online
        case rootPath = "root_path"
    }
}

// MARK: - Client

enum APIError: Error, CustomStringConvertible {
    case http(Int, String)
    case engineUnreachable

    var description: String {
        switch self {
        case .http(let status, let message):
            return "engine error \(status): \(message)"
        case .engineUnreachable:
            return "engine not running — start it with: python -m shootr.api"
        }
    }
}

/// Thin async client over the local engine. M4 assumes the engine is
/// already running (design 12 §6).
struct APIClient: Sendable {
    let base = URL(string: "http://127.0.0.1:8721")!

    private func request<T: Decodable>(
        _ method: String, _ path: String, body: Data? = nil
    ) async throws -> T {
        var req = URLRequest(url: base.appendingPathComponent(path))
        req.httpMethod = method
        req.httpBody = body
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Scanning a large library is synchronous in the engine and can run
        // past URLSession's 60 s default. Timing out there left the app
        // silent while the scan completed server-side — the request must
        // outlive the scan, not the other way around.
        req.timeoutInterval = 600
        let (data, resp): (Data, URLResponse)
        do {
            (data, resp) = try await URLSession.shared.data(for: req)
        } catch {
            throw APIError.engineUnreachable
        }
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let msg = String(data: data, encoding: .utf8) ?? ""
            throw APIError.http(status, msg)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    func shoots() async throws -> [Shoot] {
        try await request("GET", "api/shoots")
    }

    func libraries() async throws -> [Library] {
        try await request("GET", "api/libraries")
    }

    func groups(shootId: Int) async throws -> [PhotoGroup] {
        try await request("GET", "api/shoots/\(shootId)/groups")
    }

    func photo(_ id: Int) async throws -> PhotoDetail {
        try await request("GET", "api/photos/\(id)")
    }

    func selection(_ id: Int) async throws -> Selection {
        try await request("GET", "api/selections/\(id)")
    }

    struct OverrideBody: Codable { let state: String }
    struct OverrideResponse: Codable {
        let photoId: Int
        enum CodingKeys: String, CodingKey { case photoId = "photo_id" }
    }

    func override(selectionId: Int, photoId: Int, state: String)
        async throws -> OverrideResponse {
        let body = try JSONEncoder().encode(OverrideBody(state: state))
        return try await request(
            "PATCH", "api/selections/\(selectionId)/entries/\(photoId)",
            body: body)
    }

    func thumbURL(photoId: Int, size: Int) -> URL {
        base.appendingPathComponent("api/photos/\(photoId)/thumb")
            .appending(queryItems: [.init(name: "size", value: "\(size)")])
    }

    // MARK: library management (native replaces the web control panel)

    struct AddLibraryBody: Codable { let rootPath: String
        enum CodingKeys: String, CodingKey { case rootPath = "root_path" } }
    struct ScanCounts: Codable {
        let added: Int
        let unchanged: Int
        let errors: Int
    }
    struct AddLibraryResponse: Codable {
        let id: Int
        let scan: ScanCounts
    }

    func addLibrary(rootPath: String) async throws -> AddLibraryResponse {
        let body = try JSONEncoder().encode(AddLibraryBody(rootPath: rootPath))
        return try await request("POST", "api/libraries", body: body)
    }

    struct DeleteResponse: Codable { let deleted: Int }

    func deleteLibrary(_ id: Int) async throws -> DeleteResponse {
        try await request("DELETE", "api/libraries/\(id)")
    }

    struct Proposal: Codable {
        let photoIds: [Int]
        let start: String?
        let end: String?
        let directories: [String]
        enum CodingKeys: String, CodingKey {
            case start, end, directories
            case photoIds = "photo_ids"
        }
    }

    func proposals(libraryId: Int) async throws -> [Proposal] {
        try await request("GET", "api/libraries/\(libraryId)/shoot-proposals")
    }

    struct CreateShootBody: Codable {
        let libraryId: Int
        let name: String
        let profile: String
        let photoIds: [Int]
        enum CodingKeys: String, CodingKey {
            case name, profile
            case libraryId = "library_id"
            case photoIds = "photo_ids"
        }
    }
    struct CreateShootResponse: Codable { let id: Int }

    func createShoot(libraryId: Int, name: String, profile: String,
                     photoIds: [Int]) async throws -> CreateShootResponse {
        let body = try JSONEncoder().encode(CreateShootBody(
            libraryId: libraryId, name: name, profile: profile,
            photoIds: photoIds))
        return try await request("POST", "api/shoots", body: body)
    }

    struct AnalyzeResponse: Codable {
        let jobId: Int
        let total: Int
        enum CodingKeys: String, CodingKey {
            case total
            case jobId = "job_id"
        }
    }

    func analyze(shootId: Int) async throws -> AnalyzeResponse {
        try await request("POST", "api/shoots/\(shootId)/analyze")
    }

    struct JobStatus: Codable {
        let state: String
        let total: Int
        let completed: Int
        let failed: Int
    }

    func jobStatus(_ id: Int) async throws -> JobStatus {
        try await request("GET", "api/jobs/\(id)")
    }

    // MARK: export (design 07 §3 / 10 §2 — engine decides, client displays)

    struct ExportConflict: Codable {
        let path: String
        let oldRating: Int?
        let newRating: Int?
        enum CodingKeys: String, CodingKey {
            case path
            case oldRating = "old_rating"
            case newRating = "new_rating"
        }
    }

    struct ExportPreview: Codable {
        let newSidecars: Int
        let updates: Int
        let conflicts: [ExportConflict]
        let skippedDng: [String]
        let unchanged: Int
        let backupDir: String
        enum CodingKeys: String, CodingKey {
            case updates, conflicts, unchanged
            case newSidecars = "new_sidecars"
            case skippedDng = "skipped_dng"
            case backupDir = "backup_dir"
        }
    }

    func exportPreview(selectionId: Int) async throws -> ExportPreview {
        try await request(
            "POST", "api/selections/\(selectionId)/export/preview")
    }

    struct ExportBody: Codable {
        let confirmOverwrite: Bool
        enum CodingKeys: String, CodingKey {
            case confirmOverwrite = "confirm_overwrite"
        }
    }
    struct ExportResult: Codable {
        let written: Int
        let skippedDng: [String]
        let unchanged: Int
        enum CodingKeys: String, CodingKey {
            case written, unchanged
            case skippedDng = "skipped_dng"
        }
    }

    func export(selectionId: Int, confirmOverwrite: Bool)
        async throws -> ExportResult {
        let body = try JSONEncoder().encode(
            ExportBody(confirmOverwrite: confirmOverwrite))
        return try await request(
            "POST", "api/selections/\(selectionId)/export", body: body)
    }

    // MARK: shoot settings

    struct ShootPatchBody: Codable {
        let name: String?
        let profile: String?
    }
    struct ShootPatchResponse: Codable {
        let id: Int
        let rescored: Int
    }

    func patchShoot(_ id: Int, name: String? = nil, profile: String? = nil)
        async throws -> ShootPatchResponse {
        let body = try JSONEncoder().encode(
            ShootPatchBody(name: name, profile: profile))
        return try await request("PATCH", "api/shoots/\(id)", body: body)
    }

    struct SharpnessMap: Codable {
        let tiles: [[Double]]?
        let max: Double?
    }

    func sharpnessMap(photoId: Int) async throws -> SharpnessMap {
        try await request("GET", "api/photos/\(photoId)/sharpness-map")
    }
}
