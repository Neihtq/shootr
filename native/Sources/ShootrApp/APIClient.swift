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

// MARK: - Style models (design 08 §7b)
//
// A style model is the user's object: a name, a method, the libraries its
// history comes from, its knobs, and the metrics ONE harness measured for it.
// Everything below is a mirror. The client does not decide which method fits,
// which model is better, or what a number means — the engine says all three,
// and rule 6 is the reason the comparison screen prints its numbers instead of
// reducing them.

/// A method knob exactly as the engine sent it. The registry's defaults are
/// mixed types (`k` an integer, `tau` a float, `lambda` null meaning "choose
/// it by cross-validation at fit time"), and the client's only job is to show
/// them back, so they are kept as decoded rather than coerced into a number
/// that would misreport what the engine holds.
enum StyleParamValue: Codable, Equatable {
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let v = try? c.decode(Bool.self) { self = .bool(v); return }
        if let v = try? c.decode(Int.self) { self = .int(v); return }
        if let v = try? c.decode(Double.self) { self = .double(v); return }
        self = .string(try c.decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .bool(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .double(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }

    /// Typography, not arithmetic. A null knob shows as "—": the engine has
    /// no value stored for it yet, which is not the same as zero (rule 8).
    var display: String {
        switch self {
        case .bool(let v): return v ? "yes" : "no"
        case .int(let v): return "\(v)"
        case .double(let v):
            return v == v.rounded() ? "\(Int(v))"
                : String(format: "%g", v)
        case .string(let v): return v
        case .null: return "—"
        }
    }
}

/// One entry of the method registry (`GET /api/style/methods`). `fits` and
/// `explainsByNeighbours` come from the engine per method and are never
/// inferred here from the method's name: the trade-off between them is the
/// whole point of the choice the user is being asked to make (§7b).
struct StyleMethod: Codable, Identifiable {
    let method: String
    let defaultParams: [String: StyleParamValue]
    /// Learning runs a fitting step over the history first.
    let fits: Bool
    /// A prediction from this method can name the history photos it came from.
    let explainsByNeighbours: Bool

    var id: String { method }

    enum CodingKeys: String, CodingKey {
        case method, fits
        case defaultParams = "default_params"
        case explainsByNeighbours = "explains_by_neighbours"
    }
}

/// One parameter's held-out error against the family-median baseline.
/// `baselineMae` is nil when the harness had no baseline for it — rendered as
/// "—", never as a zero that would read as a perfect baseline.
struct StyleParamMetric: Codable {
    let mae: Double
    let baselineMae: Double?
    let n: Int

    enum CodingKeys: String, CodingKey {
        case mae, n
        case baselineMae = "baseline_mae"
    }
}

/// What §7's harness measured for one model. Every field is optional because
/// an untrained model carries `metrics: {}` — an absent measurement is shown
/// as absent rather than as a zero score.
struct StyleModelMetrics: Codable {
    let historyN: Int?
    let families: Int?
    let coverage: Double?
    /// How many scored parameters beat the family median. The engine counts
    /// this; the client does not recount it (rule 6).
    let beatsMedianOn: Int?
    let paramsScored: Int?
    let heldOut: Bool?
    /// `shot_group` = whole bursts held out, `photo` = one frame at a time.
    /// The distinction changes the numbers enough to flip a choice (§7b), so
    /// it is stated wherever they are shown.
    let heldOutBy: String?
    let lambda: Double?
    let perParam: [String: StyleParamMetric]?

    var measured: Bool { !(perParam?.isEmpty ?? true) }

    enum CodingKeys: String, CodingKey {
        case families, coverage, lambda
        case historyN = "history_n"
        case beatsMedianOn = "beats_median_on"
        case paramsScored = "params_scored"
        case heldOut = "held_out"
        case heldOutBy = "held_out_by"
        case perParam = "per_param"
    }
}

struct StyleModelInfo: Codable, Identifiable {
    let id: Int
    let name: String
    let method: String
    /// Empty = every library. The scope, resolved to paths for display.
    let libraryIds: [Int]
    let params: [String: StyleParamValue]
    let metrics: StyleModelMetrics
    let historyN: Int
    let processVersion: String?
    /// Engine timestamp; nil = never learned. Shown verbatim.
    let trainedAt: String?
    let trained: Bool
    let isActive: Bool
    /// The engine's own statement about this model's method, so a fitted
    /// model's rows can say what they can't show (§7a).
    let explainsByNeighbours: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, method, params, metrics, trained
        case libraryIds = "library_ids"
        case historyN = "history_n"
        case processVersion = "process_version"
        case trainedAt = "trained_at"
        case isActive = "is_active"
        case explainsByNeighbours = "explains_by_neighbours"
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
    /// Empty for a fitted method, which has no neighbours to name; the row
    /// then renders `fittedFromHistoryN` instead of an empty area (§7b).
    let neighborPhotoIds: [Int]?
    /// How much edit history the fitted model was fitted from — the engine's
    /// provenance for a prediction that cannot point at photos. Present only
    /// for a fitted method.
    let fittedFromHistoryN: Int?

    enum CodingKeys: String, CodingKey {
        case abstained, reason, confidence, params, damped, excluded
        case photoId = "photo_id"
        case neighborPhotoIds = "neighbor_photo_ids"
        case fittedFromHistoryN = "fitted_from_history_n"
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
    /// Which model produced these predictions. nil = no model was used: the
    /// engine's implicit default over all history, which is a fallback and not
    /// a choice the user made (§7b) — the UI says so rather than naming it.
    let model: StyleModelInfo?
    /// What the engine actually learned from for this preview. Compared against
    /// a model's recorded `history_n`, it is what makes "relearn" a concrete
    /// suggestion rather than a hunch.
    let history: StyleHistoryUse?
    let predictions: [StylePrediction]

    enum CodingKeys: String, CodingKey {
        case family, predictions, model, history
        case processVersion = "process_version"
        case excludedParams = "excluded_params"
    }
}

struct StyleHistoryUse: Codable {
    let used: Int
    let excludedOtherProcessVersion: Int?
    let processVersionUnverified: Bool?

    enum CodingKeys: String, CodingKey {
        case used
        case excludedOtherProcessVersion = "excluded_other_process_version"
        case processVersionUnverified = "process_version_unverified"
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
    /// Which model wrote them, echoed by the engine. nil = the implicit
    /// default; stated as such so the result names the source of the values.
    let model: StyleModelInfo?
    /// The engine's own sentence about the conflicts — shown verbatim.
    let note: String

    enum CodingKeys: String, CodingKey {
        case written, abstained, conflicts, note, model
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

    // MARK: style models (design 08 §7b — the user's objects, four operations)

    /// The method registry. Fetched rather than hard-coded: `fits` and
    /// `explains_by_neighbours` are the engine's statements about each method,
    /// and a stale copy in Swift would misdescribe the trade-off the user is
    /// choosing between.
    func styleMethods() async throws -> [StyleMethod] {
        try await request("GET", "api/style/methods")
    }

    func styleModels() async throws -> [StyleModelInfo] {
        try await request("GET", "api/style/models")
    }

    struct StyleModelBody: Codable {
        let name: String
        let method: String
        let libraryIds: [Int]
        /// Left empty: the engine merges its registry defaults, so the client
        /// never invents a knob value the user did not set.
        let params: [String: StyleParamValue]
        enum CodingKeys: String, CodingKey {
            case name, method, params
            case libraryIds = "library_ids"
        }
    }

    /// Creates AND learns in one call. 400 `unknown_method`; 409
    /// `insufficient_history`, which keeps the row — the scope may simply have
    /// no catalog imported yet, and discarding the user's choice for that would
    /// be the client deciding it was a mistake.
    func createStyleModel(name: String, method: String, libraryIds: [Int],
                          params: [String: StyleParamValue] = [:])
        async throws -> StyleModelInfo {
        let body = try JSONEncoder().encode(StyleModelBody(
            name: name, method: method, libraryIds: libraryIds,
            params: params))
        return try await request("POST", "api/style/models", body: body)
    }

    /// Relearn: same model, current history. 409 `insufficient_history`.
    func trainStyleModel(_ id: Int) async throws -> StyleModelInfo {
        try await request("POST", "api/style/models/\(id)/train")
    }

    /// Choose the default model for predictions that name none.
    func activateStyleModel(_ id: Int) async throws -> StyleModelInfo {
        try await request("POST", "api/style/models/\(id)/activate")
    }

    /// Deletes the model row only. No photo, no edit history and no sidecar is
    /// touched — the UI states that, because "delete" in a photo app has to be
    /// unambiguous (rule 2's spirit).
    func deleteStyleModel(_ id: Int) async throws -> DeleteResponse {
        try await request("DELETE", "api/style/models/\(id)")
    }

    /// `family: nil` omits the key entirely so the engine auto-suggests from
    /// scene similarity; `photoIds: nil` defaults to the shoot's latest
    /// picks. Both defaults are the engine's — the client has no business
    /// guessing a look family. `modelId: nil` is omitted too, which means the
    /// active model (design 08 §7b).
    struct StylePredictBody: Codable {
        let family: Int?
        let photoIds: [Int]?
        let modelId: Int?
        enum CodingKeys: String, CodingKey {
            case family
            case photoIds = "photo_ids"
            case modelId = "model_id"
        }
    }

    func stylePredict(shootId: Int, family: Int?, photoIds: [Int]?,
                      modelId: Int? = nil)
        async throws -> StylePredictResponse {
        let body = try JSONEncoder().encode(
            StylePredictBody(family: family, photoIds: photoIds,
                             modelId: modelId))
        return try await request(
            "POST", "api/shoots/\(shootId)/style/predict", body: body)
    }

    struct StyleExportBody: Codable {
        let family: Int
        let photoIds: [Int]
        let modelId: Int?
        enum CodingKeys: String, CodingKey {
            case family
            case photoIds = "photo_ids"
            case modelId = "model_id"
        }
    }

    /// Writes `crs:` develop attributes for the given photos. The endpoint
    /// takes no parameter list on purpose: it reads the stored opt-out itself
    /// (`PUT /api/style/preferences`) and echoes it back, so both clients
    /// write the same set. There is no conflict override — user-edited
    /// sidecars are skipped and reported. `modelId: nil` writes with the
    /// active model, the same resolution the preview used.
    func styleExportDevelop(shootId: Int, family: Int, photoIds: [Int],
                            modelId: Int? = nil)
        async throws -> StyleWriteResult {
        let body = try JSONEncoder().encode(
            StyleExportBody(family: family, photoIds: photoIds,
                            modelId: modelId))
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
