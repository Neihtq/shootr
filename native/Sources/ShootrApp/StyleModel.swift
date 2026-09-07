import Foundation
import Observation

/// View state for the style screens (design 08 §7a). Holds fetched engine
/// payloads, the cursor, and the display filters — and nothing else. There
/// is no blending, no confidence maths, no clamping and no gate here: every
/// one of those lives in the engine (rule 6). The only numbers this file
/// produces are counts of engine verdicts, which the write dialog has to
/// state, and they are counted the same way the web client counts them
/// (`web/src/components/StylePredictPanel.tsx`).
@MainActor
@Observable
final class StyleModel {
    let api = APIClient()

    /// The shoot predictions are for. Families are global — they span
    /// shoots by design, because looks are the user's, not a shoot's.
    var shootId: Int?

    var families: [StyleFamily] = []
    var familiesFault: EngineFault?
    var familiesErrorText: String?
    var loadingFamilies = false

    var prediction: StylePredictResponse?
    var predictFault: EngineFault?
    var predictErrorText: String?
    var predicting = false

    /// nil = let the engine auto-suggest the family (design 08 §3). The
    /// client never picks one on its own.
    var familyOverride: Int?

    /// Cursor in the preview list (↑↓ / J K). Reading position only — it
    /// carries no meaning to the engine.
    var cursor = 0

    var showWrite = false
    var writing = false
    var writeResult: StyleWriteResult?
    var writeErrorText: String?

    // MARK: display filters (per-parameter, persisted)
    //
    // Deliberately not called an opt-out. The engine's export endpoint takes
    // no parameter list, so a hidden parameter is still written; the copy
    // says so in the preview and again in the write dialog. Same default and
    // same storage key as the web client (`web/src/style.ts`), which stores
    // it in localStorage — separate stores, one behaviour.
    // `ColorGradeMidtoneHue` ships hidden because the family median
    // measurably beats k-NN on it
    // (docs/benchmarks/2026-08-30-style-knn-eval.md).

    private static let hiddenKey = "shootr.style.hiddenParams"
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

    // MARK: derived views of engine data (counts of verdicts, nothing more)

    var predictions: [StylePrediction] { prediction?.predictions ?? [] }

    var predicted: [StylePrediction] { predictions.filter { !$0.abstained } }

    var abstainingCount: Int { predictions.count { $0.abstained } }

    var current: StylePrediction? {
        predictions.indices.contains(cursor) ? predictions[cursor] : nil
    }

    /// Family actually in force: the engine's echo, so an auto-suggestion
    /// is displayed as the concrete family it resolved to.
    var effectiveFamily: Int? { prediction?.family }

    /// Photos the write covers — every photo the engine predicted for, in
    /// preview order. Same set the web client sends.
    var writeIds: [Int] { predicted.map(\.photoId) }

    /// The parameters the engine actually returned, in the shared display
    /// order. Never a hardcoded list of what we expect: if the engine starts
    /// predicting another slider it appears here instead of being silently
    /// dropped from the preview.
    var paramNames: [String] {
        var names: Set<String> = []
        for p in predictions {
            if let params = p.params { names.formUnion(params.keys) }
        }
        return StyleParams.ordered(names)
    }

    /// Parameters the user switched off that the engine will nevertheless
    /// write — named in the write dialog rather than quietly dropped.
    var hiddenPresentParams: [String] {
        paramNames.filter { hiddenParams.contains($0) }
    }

    func isHidden(_ param: String) -> Bool { hiddenParams.contains(param) }

    func toggleHidden(_ param: String) {
        if hiddenParams.contains(param) {
            hiddenParams.remove(param)
        } else {
            hiddenParams.insert(param)
        }
    }

    /// Engine parameters for one photo, in display order, split into the
    /// ones shown and the count hidden by the filter.
    func shownParams(_ params: [String: Double]) -> [(String, Double)] {
        StyleParams.ordered(Set(params.keys))
            .filter { !hiddenParams.contains($0) }
            .compactMap { name in params[name].map { (name, $0) } }
    }

    // MARK: loading

    func load(shootId: Int) async {
        self.shootId = shootId
        await loadFamilies()
        // A 409 means there is no history at all; the predict call would
        // fail with the same fault, so don't fire it.
        if familiesFault?.code != "insufficient_history" {
            await predict()
        }
    }

    func loadFamilies() async {
        loadingFamilies = true
        defer { loadingFamilies = false }
        do {
            families = try await api.styleFamilies()
            familiesFault = nil
            familiesErrorText = nil
        } catch let error as APIError {
            families = []
            familiesFault = fault(from: error)
            familiesErrorText = error.description
        } catch {
            families = []
            familiesFault = nil
            familiesErrorText = String(describing: error)
        }
    }

    /// Overriding the family means re-asking the engine, never re-filtering
    /// a cached prediction here: the blend is family-conditioned, so a
    /// client-side "filter" would be a second, wrong implementation of it.
    func setFamily(_ family: Int?) async {
        guard family != familyOverride else { return }
        familyOverride = family
        await predict()
    }

    /// Re-asks the engine. Changing the family or pressing R goes back to
    /// the engine rather than re-deriving anything locally.
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
        } catch let error as APIError {
            prediction = nil
            predictFault = fault(from: error)
            predictErrorText = error.description
        } catch {
            prediction = nil
            predictFault = nil
            predictErrorText = String(describing: error)
        }
    }

    private func fault(from error: APIError) -> EngineFault? {
        if case .engine(_, let f) = error { return f }
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

    // MARK: cursor (keyboard, design 12 §4a)

    func moveCursor(_ delta: Int) {
        guard !predictions.isEmpty else { return }
        cursor = min(predictions.count - 1, max(0, cursor + delta))
    }

    func cursorToStart() { cursor = 0 }

    func cursorToEnd() { cursor = max(0, predictions.count - 1) }
}

/// `crs:` parameter presentation, mirroring `web/src/style.ts` exactly: the
/// same labels, the same order (Lightroom's panel order), the same signed
/// formatting and units. Two clients that name or round the user's sliders
/// differently are two clients the user has to reconcile by hand.
///
/// Typography, not arithmetic: nothing here changes a value.
enum StyleParams {
    /// crs: name → the label Lightroom shows. Unknown keys fall through as
    /// themselves, so the engine's list can grow without this table
    /// silently hiding a parameter that is about to be written.
    static let labels: [(name: String, label: String)] = [
        ("Exposure2012", "Exposure"),
        ("Contrast2012", "Contrast"),
        ("Highlights2012", "Highlights"),
        ("Shadows2012", "Shadows"),
        ("Whites2012", "Whites"),
        ("Blacks2012", "Blacks"),
        ("Texture", "Texture"),
        ("Clarity2012", "Clarity"),
        ("Dehaze", "Dehaze"),
        ("Vibrance", "Vibrance"),
        ("Saturation", "Saturation"),
        ("ColorGradeMidtoneHue", "Color grade · midtone hue"),
        ("ColorGradeMidtoneSat", "Color grade · midtone saturation"),
    ]

    static func label(_ name: String) -> String {
        labels.first { $0.name == name }?.label ?? name
    }

    /// Exposure is in EV and moves in tenths; the rest are Lightroom's ±100
    /// slider units. Signed, because the direction is the interesting part.
    static func format(_ name: String, _ value: Double) -> String {
        let digits = name == "Exposure2012" ? 2 : 1
        let s = String(format: "%.\(digits)f", value)
        return value > 0 ? "+\(s)" : s
    }

    static func unit(_ name: String) -> String {
        name == "Exposure2012" ? " EV" : ""
    }

    static func chip(_ name: String, _ value: Double) -> String {
        "\(label(name)) \(format(name, value))\(unit(name))"
    }

    /// Known parameters in the table's order (which is the engine's order,
    /// which is Lightroom's panel order); anything unknown after them,
    /// alphabetically, so a new engine parameter is visible rather than lost.
    /// Swift dictionaries don't keep JSON order, so the order is restored
    /// here instead of being invented per view.
    static func ordered(_ names: Set<String>) -> [String] {
        let known = labels.map(\.name).filter(names.contains)
        let unknown = names.subtracting(known).sorted()
        return known + unknown
    }
}
