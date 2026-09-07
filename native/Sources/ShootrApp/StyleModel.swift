import Foundation
import Observation

/// View state for the style screens (design 08 §7a). Holds fetched engine
/// payloads and the cursor — and nothing else. There is no blending, no
/// confidence maths, no clamping and no gate here: every one of those lives
/// in the engine (rule 6). The only numbers this file produces are counts of
/// engine verdicts, which the write dialog has to state, and they are counted
/// the same way the web client counts them
/// (`web/src/components/StylePredictPanel.tsx`).
///
/// The per-parameter opt-out is engine state too (design 08 §6/§7a): it is
/// fetched, PUT, and re-read here, never held locally. It changes what lands
/// in the user's files, so a client-local copy would let the two clients
/// write different edits.
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

    // MARK: per-parameter opt-out (engine state, design 08 §6/§7a)

    /// What the engine says it can predict — the toggle list. Taken from the
    /// engine rather than from the parameters a prediction happened to carry:
    /// an excluded parameter is absent from `params`, so deriving the list
    /// from predictions would make it impossible to switch back on.
    var modelableParams: [String] = []

    /// The engine's stored exclusions. Only ever assigned from a GET or a PUT
    /// response, so the checkboxes show stored state, not local intent.
    var excludedParams: Set<String> = []

    /// The engine answered the GET. The toggles are not drawn before that:
    /// guessing a list here and letting the user click it would be guessing
    /// about their files.
    var prefsLoaded = false
    /// A PUT is in flight — every checkbox is disabled until the engine has
    /// stored the change and the re-predict has landed.
    var savingPrefs = false
    /// A REFUSED PUT only (`unknown_param`, or an unreachable engine on that
    /// call). Nothing was stored when this is set.
    var prefsFault: EngineFault?
    var prefsErrorText: String?

    /// Measured exclusion suggestions the user has not taken up: the engine's
    /// stored list is authoritative, so these are proposed with their evidence
    /// and applied only on a click. Same map, same reasons, same one-click
    /// shape as the web client's `SUGGESTED_EXCLUSIONS`.
    var suggestedExclusions: [String] {
        StyleCopy.suggestedExclusions.keys
            .filter { modelableParams.contains($0)
                      && !excludedParams.contains($0) }
            .sorted()
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

    /// Every parameter name the predictions carried, predicted or withheld,
    /// in the engine's own order of appearance.
    var returnedParamNames: [String] {
        var seen: [String] = []
        for p in predictions {
            for name in (p.params.map { StyleParams.ordered(Set($0.keys)) }
                         ?? [])
                + (p.excluded.map { StyleParams.ordered(Set($0.keys)) } ?? []) {
                if !seen.contains(name) { seen.append(name) }
            }
        }
        return seen
    }

    /// The rows in the parameter box: the engine's modelable list (which is
    /// also the PUT allowlist, hence exactly what can be toggled), then
    /// anything it returned that is somehow outside that list — shown
    /// read-only rather than quietly missing from the panel.
    var paramNames: [String] {
        modelableParams
            + returnedParamNames.filter { !modelableParams.contains($0) }
    }

    func isModelable(_ param: String) -> Bool {
        modelableParams.contains(param)
    }

    /// The exclusion the engine applied to the preview on screen, in the order
    /// it reported. From the predict response rather than the locally-held set,
    /// so the write dialog's promise comes from the same call as the numbers.
    var excludedInPreview: [String] {
        prediction?.excludedParams ?? excludedParams.sorted()
    }

    /// Previewed photos where a value was actually withheld. "You excluded a
    /// parameter" and "it affected these photos" are different facts, and the
    /// write dialog states both.
    var withheldCount: Int {
        predictions.count { !($0.excluded?.isEmpty ?? true) }
    }

    func isExcluded(_ param: String) -> Bool { excludedParams.contains(param) }

    /// Engine parameters for one photo in display order. Ordering only — the
    /// engine already removed the excluded ones from `params` and moved them,
    /// with their predicted values, to `excluded`.
    func orderedParams(_ params: [String: Double]) -> [(String, Double)] {
        StyleParams.ordered(Set(params.keys))
            .compactMap { name in params[name].map { (name, $0) } }
    }

    // MARK: loading

    func load(shootId: Int) async {
        self.shootId = shootId
        // Preferences first: they decide what the predictions contain.
        await loadPreferences()
        await loadFamilies()
        // A 409 means there is no history at all; the predict call would
        // fail with the same fault, so don't fire it.
        if familiesFault?.code != "insufficient_history" {
            await predict()
        }
    }

    /// Reads the stored exclusions and the engine's modelable list. A failure
    /// leaves `prefsLoaded` false and the toggles undrawn — the same as the web
    /// client, which renders the box only once the GET has answered. The
    /// preview and the write dialog still report the engine's own
    /// `excluded_params`, so the user is never told the wrong thing about their
    /// files; they are just not offered controls we cannot validate.
    func loadPreferences() async {
        do {
            let prefs = try await api.stylePreferences()
            modelableParams = prefs.modelableParams
            excludedParams = Set(prefs.excludedParams)
            prefsLoaded = true
        } catch {
            // Keep a list we already have: dropping it would pull the toggles
            // out from under the message explaining why a change failed.
            if modelableParams.isEmpty { prefsLoaded = false }
        }
    }

    /// Flips one parameter and re-asks the engine. Excluding a parameter
    /// changes the payload — the value moves out of `params` and into
    /// `excluded` — so the predictions on screen are refetched rather than
    /// re-filtered here.
    func setExcluded(_ param: String, _ excluded: Bool) async {
        guard !savingPrefs else { return }
        guard excluded != excludedParams.contains(param) else { return }
        var next = excludedParams
        if excluded { next.insert(param) } else { next.remove(param) }
        await putExcluded(next.sorted())
    }

    /// Accepting a measured suggestion — the same PUT any other checkbox
    /// makes, just prefilled.
    func acceptSuggestion(_ param: String) async {
        await setExcluded(param, true)
    }

    private func putExcluded(_ next: [String]) async {
        savingPrefs = true
        defer { savingPrefs = false }
        prefsFault = nil
        prefsErrorText = nil
        do {
            excludedParams = Set(
                try await api.setStylePreferences(excludedParams: next))
        } catch let error as APIError {
            // 400 `unknown_param` (or the engine gone): nothing was stored.
            // Show its sentence and put the checkboxes back to stored truth.
            prefsFault = fault(from: error)
            prefsErrorText = error.description
            await loadPreferences()
            return
        } catch {
            prefsFault = nil
            prefsErrorText = String(describing: error)
            await loadPreferences()
            return
        }
        await predict()
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
