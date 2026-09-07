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
    let analyzedCount: Int
    /// Non-nil while analysis/culling is in flight. Server-derived, so it
    /// survives a relaunch and agrees with the web UI.
    let busyJobId: Int?
    /// Why a stopped analyze job stopped (`volume_offline`, `helper_failed`,
    /// `interrupted_restart`). Non-nil means partial work is checkpointed
    /// and re-running resumes it — never shown as "not culled yet".
    let stoppedReason: String?

    /// Opening a shoot mid-cull shows an empty or half-built review — there
    /// are no groups until the chained steps run.
    var isBusy: Bool { busyJobId != nil }
    /// Culled at least once, so there is something to browse.
    var isReviewable: Bool { !isBusy && latestSelectionId != nil }
    /// Stopped partway with work banked: the action resumes, not restarts.
    var isStopped: Bool { !isBusy && stoppedReason != nil }

    /// Stop reason in the user's terms. An unrecognized reason renders as
    /// itself rather than disappearing — silence reads as "nothing happened".
    var stoppedLabel: String? {
        switch stoppedReason {
        case nil: return nil
        case "volume_offline": return "paused — drive disconnected"
        case "helper_failed": return "stopped — analysis error"
        case "interrupted_restart": return "stopped — app restarted"
        case let other: return other
        }
    }

    enum CodingKeys: String, CodingKey {
        case id, name, profile
        case photoCount = "photo_count"
        case latestSelectionId = "latest_selection_id"
        case analyzedCount = "analyzed_count"
        case busyJobId = "busy_job_id"
        case stoppedReason = "stopped_reason"
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

// MARK: - Style learning (design 08 §7a)
//
// Mirrors only. Every number here — traits, medians, confidence, the
// neighbour ids, the abstain reason — is the engine's. The client renders
// them; it never blends, gates, or clamps anything (design 08 §7a, 10 §1).

struct StyleFamily: Codable, Identifiable {
    let id: Int
    let size: Int
    /// Engine-written trait label, e.g. "+Highlights2012 +Exposure2012".
    /// Rendered verbatim — restating it in our own words is how two clients
    /// start describing the same family differently.
    let traits: String
    let samplePhotoIds: [Int]
    let median: [String: Double]

    enum CodingKeys: String, CodingKey {
        case id, size, traits, median
        case samplePhotoIds = "sample_photo_ids"
    }
}

/// The per-parameter opt-out, which lives in the engine (design 08 §6/§7a).
/// It decides what lands in the user's files, so it cannot be a client
/// setting: web and native would then write different edits from the same
/// click. `modelableParams` is the engine's own list of what it can predict —
/// the only honest source for the toggle list, and the set the PUT validates
/// against.
struct StylePreferences: Codable {
    let excludedParams: [String]
    let modelableParams: [String]

    enum CodingKeys: String, CodingKey {
        case excludedParams = "excluded_params"
        case modelableParams = "modelable_params"
    }
}

/// The PUT echo: what the engine now holds. Applied to the UI instead of the
/// value we sent, so the toggles always show stored state.
struct StyleExcludedParams: Codable {
    let excludedParams: [String]

    enum CodingKeys: String, CodingKey {
        case excludedParams = "excluded_params"
    }
}

/// One photo's prediction. `abstained` is a first-class state, not an
/// empty result: `params` nil/empty with `abstained == true` means "no
/// confident prediction", never "no changes needed" (design 08 §7a).
struct StylePrediction: Codable {
    let photoId: Int
    let abstained: Bool
    /// `low_confidence` · `no_similar_history` · `family_too_small` ·
    /// `not_analyzed`. nil when the engine predicted.
    let reason: String?
    let confidence: Double?
    let params: [String: Double]?
    /// Guardrails that fired, per parameter: `{param: engine's sentence}`
    /// (design 08 §6 — the highlight-clip check withholds a positive
    /// exposure push). Rendered, never inferred: a parameter that was
    /// silently changed to 0 would be exactly the opaque number rule 5
    /// forbids.
    let damped: [String: String]?
    /// Parameters the engine DID predict and will NOT write, because the user
    /// excluded them: `{param: predicted value}` (design 08 §6). A different
    /// statement from an abstention — there is a number, it is just not going
    /// into the file — so it is rendered with its value, never dropped.
    let excluded: [String: Double]?
    /// The history photos the blend came from — the explanation for the
    /// numbers (design 08 §4). Present even for a low-confidence abstention.
    let neighborPhotoIds: [Int]?

    enum CodingKeys: String, CodingKey {
        case abstained, reason, confidence, params, damped, excluded
        case photoId = "photo_id"
        case neighborPhotoIds = "neighbor_photo_ids"
    }
}

struct StylePredictResponse: Codable {
    /// The family actually used — the auto-suggestion when none was sent.
    let family: Int
    let processVersion: String
    /// The opt-out the engine applied to THIS preview. Rendered in the write
    /// dialog rather than the locally-held set, so what the dialog promises
    /// comes from the same call the numbers came from.
    let excludedParams: [String]
    let predictions: [StylePrediction]

    enum CodingKeys: String, CodingKey {
        case family, predictions
        case processVersion = "process_version"
        case excludedParams = "excluded_params"
    }
}

struct StyleAbstention: Codable {
    let photoId: Int
    let reason: String?
    enum CodingKeys: String, CodingKey {
        case reason
        case photoId = "photo_id"
    }
}

/// A sidecar already holding the user's own develop settings. Reported and
/// skipped; there is deliberately no override parameter on this path
/// (design 08 §6), so the UI offers no control for it either.
struct StyleConflict: Codable {
    let photoId: Int
    let path: String
    enum CodingKeys: String, CodingKey {
        case path
        case photoId = "photo_id"
    }
}

struct StyleWriteResult: Codable {
    let written: [Int]
    let abstained: [StyleAbstention]
    let conflicts: [StyleConflict]
    /// The opt-out the engine applied to this write — reported so the result
    /// says what was left out, not only what went in.
    let excludedParams: [String]
    /// The engine's own sentence about the conflicts — shown verbatim.
    let note: String

    enum CodingKeys: String, CodingKey {
        case written, abstained, conflicts, note
        case excludedParams = "excluded_params"
    }
}

// MARK: - Client

/// The engine's structured error body (`{"detail": {code, message, …}}`).
/// Decoding it is what lets the UI answer `insufficient_history` with useful
/// copy instead of dumping a JSON blob at the user.
struct EngineFault: Codable {
    let code: String
    let message: String
    let retryable: Bool?
}

private struct EngineFaultEnvelope: Codable {
    let detail: EngineFault
}

enum APIError: Error, CustomStringConvertible {
    case http(Int, String)
    case engine(Int, EngineFault)
    case engineUnreachable

    var description: String {
        switch self {
        case .http(let status, let message):
            return "engine error \(status): \(message)"
        case .engine(_, let fault):
            return fault.message
        case .engineUnreachable:
            return "engine not running — start it with: python -m shootr.api"
        }
    }

    /// Engine error code when there is one (`insufficient_history`,
    /// `no_selection`, `not_analyzed`, …), so views can map it to copy.
    var code: String? {
        if case .engine(_, let fault) = self { return fault.code }
        return nil
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
            if let env = try? JSONDecoder().decode(
                EngineFaultEnvelope.self, from: data) {
                throw APIError.engine(status, env.detail)
            }
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

    /// Full-res eye-band crop (design 11 §3). `eye` is subject-relative,
    /// matching the keys in `FaceInfo.eyes`.
    func eyeCropURL(photoId: Int, face: Int, eye: String) -> URL {
        base.appendingPathComponent("api/photos/\(photoId)/eye-crop")
            .appending(queryItems: [.init(name: "face", value: "\(face)"),
                                    .init(name: "eye", value: eye)])
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
        let skippedEmbedded: [String]
        let unchanged: Int
        let backupDir: String
        enum CodingKeys: String, CodingKey {
            case updates, conflicts, unchanged
            case newSidecars = "new_sidecars"
            case skippedEmbedded = "skipped_embedded"
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
        let skippedEmbedded: [String]
        let unchanged: Int
        enum CodingKeys: String, CodingKey {
            case written, unchanged
            case skippedEmbedded = "skipped_embedded"
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

    // MARK: style (design 08 §7a — engine predicts, client renders)

    func styleFamilies() async throws -> [StyleFamily] {
        try await request("GET", "api/style/families")
    }

    /// The stored per-parameter opt-out plus the engine's modelable list.
    func stylePreferences() async throws -> StylePreferences {
        try await request("GET", "api/style/preferences")
    }

    struct StylePrefsBody: Codable {
        let excludedParams: [String]
        enum CodingKeys: String, CodingKey {
            case excludedParams = "excluded_params"
        }
    }

    /// Replaces the whole exclusion set (there is no per-name endpoint), and
    /// returns what the engine stored. A name outside `modelable_params` is a
    /// 400 `unknown_param` and nothing is stored.
    func setStylePreferences(excludedParams: [String]) async throws
        -> [String] {
        let body = try JSONEncoder().encode(
            StylePrefsBody(excludedParams: excludedParams))
        let r: StyleExcludedParams = try await request(
            "PUT", "api/style/preferences", body: body)
        return r.excludedParams
    }

    /// `family: nil` omits the key entirely so the engine auto-suggests from
    /// scene similarity; `photoIds: nil` defaults to the shoot's latest
    /// picks. Both defaults are the engine's — the client has no business
    /// guessing a look family.
    struct StylePredictBody: Codable {
        let family: Int?
        let photoIds: [Int]?
        enum CodingKeys: String, CodingKey {
            case family
            case photoIds = "photo_ids"
        }
    }

    func stylePredict(shootId: Int, family: Int?, photoIds: [Int]?)
        async throws -> StylePredictResponse {
        let body = try JSONEncoder().encode(
            StylePredictBody(family: family, photoIds: photoIds))
        return try await request(
            "POST", "api/shoots/\(shootId)/style/predict", body: body)
    }

    struct StyleExportBody: Codable {
        let family: Int
        let photoIds: [Int]
        enum CodingKeys: String, CodingKey {
            case family
            case photoIds = "photo_ids"
        }
    }

    /// Writes `crs:` develop attributes for the given photos. The endpoint
    /// takes no parameter list on purpose: it reads the stored opt-out itself
    /// (`PUT /api/style/preferences`) and echoes it back, so both clients
    /// write the same set. There is no conflict override — user-edited
    /// sidecars are skipped and reported.
    func styleExportDevelop(shootId: Int, family: Int, photoIds: [Int])
        async throws -> StyleWriteResult {
        let body = try JSONEncoder().encode(
            StyleExportBody(family: family, photoIds: photoIds))
        return try await request(
            "POST", "api/shoots/\(shootId)/style/export-develop", body: body)
    }

    struct SharpnessMap: Codable {
        let tiles: [[Double]]?
        let max: Double?
    }

    func sharpnessMap(photoId: Int) async throws -> SharpnessMap {
        try await request("GET", "api/photos/\(photoId)/sharpness-map")
    }
}
