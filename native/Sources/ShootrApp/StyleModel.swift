import Foundation
import Observation

/// View state for the style screens (design 08 §7a). Holds fetched engine
/// payloads, the user's cursor, the user's write set, and the display
/// filters — and nothing else. There is no blending, no confidence maths,
/// no clamping and no gate here: every one of those lives in the engine
/// (design 08 §7a, rule 6). The only numbers this file produces are counts
/// of engine verdicts, which the write dialog has to state.
@MainActor
@Observable
final class StyleModel {
    let api = APIClient()

    enum Pane: Hashable { case families, predict }
    var pane: Pane = .predict

    /// The shoot predictions are for. Families are global — they span
    /// shoots by design, because looks are the user's, not a shoot's.
    var shootId: Int?

    var families: [StyleFamily] = []
    var familiesFault: EngineFault?
    var loadingFamilies = false

    var prediction: StylePredictResponse?
    var predictFault: EngineFault?
    var predictErrorText: String?
    var predicting = false

    /// nil = let the engine auto-suggest the family (design 08 §3). The
    /// user can override; the client never picks one on its own.
    var familyOverride: Int?

    /// Cursor in the prediction list (↑↓ / J K).
    var cursor = 0
    /// Photos the user has taken out of the write set (Space).
    var excluded: Set<Int> = []

    var showWrite = false
    var writing = false
    var writeResult: StyleWriteResult?
    var writeErrorText: String?

    // MARK: display filters (per-parameter, persisted)
    //
    // These are DISPLAY filters, deliberately not called an opt-out: the
    // engine's export endpoint takes no parameter list, so a hidden
    // parameter is still written. `ColorGradeMidtoneHue` ships hidden
    // because the family median measurably beats k-NN on it
    // (docs/benchmarks/2026-08-30-style-knn-eval.md), which is exactly the
    // parameter a real opt-out would drop — the UI says so plainly instead
    // of pretending the write honours it.

    private static let hiddenKey = "style.hiddenParams"
    static let defaultHidden: Set<String> = ["ColorGradeMidtoneHue"]

    var hiddenParams: Set<String> {
        didSet {
            UserDefaults.standard.set(Array(hiddenParams).sorted(),
                                      forKey: Self.hiddenKey)
        }
    }

    init() {
        if let saved = UserDefaults.standard.array(
            forKey: Self.hiddenKey) as? [String] {
            hiddenParams = Set(saved)
        } else {
            hiddenParams = Self.defaultHidden
        }
    }

    // MARK: derived views of engine data (no arithmetic on predictions)

    var predictions: [StylePrediction] { prediction?.predictions ?? [] }

    var current: StylePrediction? {
        predictions.indices.contains(cursor) ? predictions[cursor] : nil
    }

    /// Family actually in force: the engine's echo, so an auto-suggestion
    /// is displayed as the concrete family it resolved to.
    var effectiveFamily: Int? { prediction?.family }

    var effectiveFamilyInfo: StyleFamily? {
        guard let f = effectiveFamily else { return nil }
        return families.first { $0.id == f }
    }

    /// Photos that would be written: the engine predicted for them and the
    /// user has not excluded them. Abstentions can never enter this set.
    var writeIds: [Int] {
        predictions
            .filter { !$0.abstained && !excluded.contains($0.photoId) }
            .map(\.photoId)
    }

    var abstainingCount: Int { predictions.count { $0.abstained } }

    var excludedCount: Int {
        predictions.count { !$0.abstained && excluded.contains($0.photoId) }
    }

    /// Every parameter the engine has mentioned in this preview, plus any
    /// the user has hidden (so a hidden one stays visible as a toggle even
    /// when no photo predicted it this time).
    var knownParams: [String] {
        var names = hiddenParams
        for p in predictions {
            if let params = p.params { names.formUnion(params.keys) }
        }
        if let median = effectiveFamilyInfo?.median {
            names.formUnion(median.keys)
        }
        return names.sorted()
    }

    func isHidden(_ param: String) -> Bool { hiddenParams.contains(param) }

    func toggleHidden(_ param: String) {
        if hiddenParams.contains(param) {
            hiddenParams.remove(param)
        } else {
            hiddenParams.insert(param)
        }
    }

    func hiddenCount(in params: [String: Double]) -> Int {
        params.keys.count { hiddenParams.contains($0) }
    }

    func visibleParams(_ params: [String: Double]) -> [(String, Double)] {
        params.filter { !hiddenParams.contains($0.key) }
            .sorted { $0.key < $1.key }
    }

    // MARK: loading

    func load(shootId: Int) async {
        self.shootId = shootId
        await loadFamilies()
        await predict()
    }

    func loadFamilies() async {
        loadingFamilies = true
        defer { loadingFamilies = false }
        do {
            families = try await api.styleFamilies()
            familiesFault = nil
        } catch let error as APIError {
            families = []
            familiesFault = fault(from: error)
        } catch {
            families = []
            familiesFault = EngineFault(
                code: "unknown", message: String(describing: error),
                retryable: nil)
        }
    }

    /// Re-asks the engine. Changing the family or pressing R goes back to
    /// the engine rather than re-deriving anything locally — a client-side
    /// re-blend would be the exact divergence rule 6 exists to prevent.
    func predict() async {
        guard let shootId else { return }
        predicting = true
        defer { predicting = false }
        do {
            // photoIds omitted: the engine predicts for the shoot's latest
            // picks, which is the set a user is about to develop.
            let r = try await api.stylePredict(
                shootId: shootId, family: familyOverride, photoIds: nil)
            prediction = r
            predictFault = nil
            predictErrorText = nil
            cursor = 0
            excluded = []
        } catch let error as APIError {
            prediction = nil
            predictFault = fault(from: error)
            predictErrorText = predictFault == nil
                ? String(describing: error) : nil
        } catch {
            prediction = nil
            predictFault = nil
            predictErrorText = String(describing: error)
        }
    }

    private func fault(from error: APIError) -> EngineFault? {
        if case .engine(_, let f) = error { return f }
        if case .engineUnreachable = error {
            return EngineFault(code: "engine_unreachable",
                               message: error.description, retryable: true)
        }
        return nil
    }

    // MARK: write

    func write() async {
        guard let shootId, let family = effectiveFamily else { return }
        let ids = writeIds
        guard !ids.isEmpty else { return }
        writing = true
        defer { writing = false }
        do {
            writeResult = try await api.styleExportDevelop(
                shootId: shootId, family: family, photoIds: ids)
            writeErrorText = nil
        } catch {
            writeErrorText = String(describing: error)
        }
    }

    // MARK: cursor / write-set (keyboard, design 12 §4a)

    func moveCursor(_ delta: Int) {
        guard !predictions.isEmpty else { return }
        cursor = min(predictions.count - 1, max(0, cursor + delta))
    }

    func cursorToStart() { cursor = 0 }

    func cursorToEnd() {
        cursor = max(0, predictions.count - 1)
    }

    /// Space: include ⇄ exclude the frame under the cursor. Abstentions are
    /// not includable — the engine has nothing to write for them.
    func toggleCurrentInclusion() {
        guard let p = current, !p.abstained else { return }
        if excluded.contains(p.photoId) {
            excluded.remove(p.photoId)
        } else {
            excluded.insert(p.photoId)
        }
    }
}
