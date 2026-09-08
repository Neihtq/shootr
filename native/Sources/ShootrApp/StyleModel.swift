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

    // MARK: style models (design 08 §7b — the user's objects)

    /// The engine's method registry. Fetched, never hard-coded: whether a
    /// method fits and whether it can name neighbour photos are the engine's
    /// statements about it.
    var methods: [StyleMethod] = []
    var models: [StyleModelInfo] = []
    /// Libraries, so a model's `library_ids` can be shown as the paths the
    /// user recognizes instead of as numbers.
    var libraries: [Library] = []
    var loadingModels = false
    /// A failed GET of the model list. Kept separate from a refused operation:
    /// one means "we don't know what models you have", the other "your click
    /// did not happen".
    var modelsErrorText: String?

    /// Which model predicts. nil = whichever the engine has active, which is
    /// also what an omitted `model_id` means, so the default is the engine's
    /// and not a second opinion held here.
    var selectedModelId: Int?

    /// A refused learn / relearn / activate / delete. Nothing changed when
    /// this is set.
    var modelFault: EngineFault?
    var modelErrorText: String?
    /// Which operation the refusal came from: `insufficient_history` means
    /// different things after a create (the row was kept) and after a relearn
    /// (the model is unchanged), and the message has to say which.
    var modelOp: StyleCopy.ModelOp = .relearn
    /// The model an operation is running on, so only its own row shows work.
    var busyModelId: Int?

    var showCompare = false

    // create form
    var showCreate = false
    var newName = ""
    var newMethod: String?
    /// Empty = every library, which is what the engine's empty `library_ids`
    /// means. Not a "select all" the client expands, because the model is
    /// meant to keep following the libraries the user adds later.
    var newLibraryIds: Set<Int> = []
    var creating = false
    var createFault: EngineFault?
    var createErrorText: String?

    /// A delete waiting on confirmation.
    var pendingDelete: StyleModelInfo?

    var selectedModel: StyleModelInfo? {
        if let selectedModelId {
            return models.first { $0.id == selectedModelId }
        }
        return models.first { $0.isActive }
    }

    /// The model the engine says produced the predictions on screen. nil means
    /// it used no model at all — its implicit default.
    var predictingModel: StyleModelInfo? { prediction?.model }

    /// Models the engine has metrics for — the comparison's columns. The test
    /// is "did the harness score any parameter", which is the engine's own
    /// answer, not a judgement about the model.
    var measuredModels: [StyleModelInfo] {
        models.filter { $0.metrics.measured }
    }

    /// Learned or not, a model with no metrics is named rather than dropped:
    /// silently missing from a comparison reads as "not measured well".
    var unmeasuredModels: [StyleModelInfo] {
        models.filter { !$0.metrics.measured }
    }

    /// The held-out splits present among the compared models. More than one
    /// means the columns were not measured the same way, which the compare
    /// sheet says out loud — comparing across splits is the mistake §7b was
    /// written to prevent.
    var comparedSplits: [String] {
        var seen: [String] = []
        for m in measuredModels {
            let by = m.metrics.heldOutBy ?? "?"
            if !seen.contains(by) { seen.append(by) }
        }
        return seen
    }

    /// Every parameter any measured model was scored on, in Lightroom's panel
    /// order — the row labels of the comparison table. Ordering only; the
    /// numbers are the engine's and are printed as they arrive.
    var comparedParamNames: [String] {
        var names: Set<String> = []
        for m in measuredModels {
            if let per = m.metrics.perParam { names.formUnion(per.keys) }
        }
        return StyleParams.ordered(names)
    }

    /// A model's scope in the user's terms: the library paths it learns from,
    /// or every library when the engine's list is empty. A library id with no
    /// matching library is named as the id — it was removed from the scan, and
    /// hiding it would understate the scope.
    func scopeLabel(_ model: StyleModelInfo) -> String {
        guard !model.libraryIds.isEmpty else { return StyleCopy.scopeAll }
        return model.libraryIds.map { id in
            libraries.first { $0.id == id }?.rootPath
                ?? StyleCopy.missingLibrary(id)
        }.joined(separator: ", ")
    }

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
        // Models first: which one predicts decides what the preview means.
        await loadModels()
        // Preferences next: they decide what the predictions contain.
        await loadPreferences()
        await loadFamilies()
        // A 409 means there is no history at all; the predict call would
        // fail with the same fault, so don't fire it.
        if familiesFault?.code != "insufficient_history" {
            await predict()
        }
    }

    // MARK: style models (learn · relearn · compare · choose, design 08 §7b)

    /// The registry, the models and the libraries their scope names. All three
    /// are engine state; nothing here is cached across a failure in a way that
    /// could show a model that no longer exists.
    func loadModels() async {
        loadingModels = true
        defer { loadingModels = false }
        do {
            methods = try await api.styleMethods()
            models = try await api.styleModels()
            libraries = try await api.libraries()
            modelsErrorText = nil
            // No method is preselected. The engine privileges none, and a
            // radio already filled in would be this client recommending one.
            // A model that is gone cannot stay selected: the next predict
            // would 404 on an id the user can no longer see.
            if let id = selectedModelId,
               !models.contains(where: { $0.id == id }) {
                selectedModelId = nil
            }
        } catch let error as APIError {
            modelsErrorText = error.description
        } catch {
            modelsErrorText = String(describing: error)
        }
    }

    /// Opens the create form on a clean slate: a refusal left over from the
    /// last attempt must not read as one about the model being described now.
    func beginCreate() {
        createFault = nil
        createErrorText = nil
        showCreate = true
    }

    /// Learn: create a model and train it in the engine's one call. A 409
    /// `insufficient_history` keeps the row, so the list is reloaded either
    /// way and the message says the model was kept.
    func createModel() async {
        let name = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, let method = newMethod, !creating else { return }
        creating = true
        defer { creating = false }
        createFault = nil
        createErrorText = nil
        do {
            let created = try await api.createStyleModel(
                name: name, method: method,
                libraryIds: newLibraryIds.sorted())
            await loadModels()
            // Predict with what was just learned — the point of making it.
            selectedModelId = created.id
            showCreate = false
            newName = ""
            newLibraryIds = []
            await predict()
        } catch let error as APIError {
            createFault = fault(from: error)
            createErrorText = error.description
            // The engine keeps the row on `insufficient_history`, so the list
            // must show it rather than pretend the click did nothing.
            await loadModels()
        } catch {
            createErrorText = String(describing: error)
            await loadModels()
        }
    }

    /// Relearn: the same model against current history. This is how new shoots
    /// take effect, on the user's say-so.
    func relearn(_ id: Int) async {
        await run(id, op: .relearn) {
            try await self.api.trainStyleModel(id)
        }
    }

    /// Choose: which model predicts when a call names none.
    func activate(_ id: Int) async {
        await run(id, op: .activate) {
            try await self.api.activateStyleModel(id)
        }
    }

    /// Relearn whatever is predicting right now — the keyboard path.
    func relearnSelected() async {
        guard let model = selectedModel else { return }
        await relearn(model.id)
    }

    private func run(_ id: Int, op: StyleCopy.ModelOp,
                     _ call: @escaping () async throws -> StyleModelInfo)
        async {
        guard busyModelId == nil else { return }
        busyModelId = id
        defer { busyModelId = nil }
        modelFault = nil
        modelErrorText = nil
        modelOp = op
        do {
            _ = try await call()
            await loadModels()
        } catch let error as APIError {
            modelFault = fault(from: error)
            modelErrorText = error.description
            await loadModels()
            return
        } catch {
            modelErrorText = String(describing: error)
            await loadModels()
            return
        }
        // The numbers on screen came from a model that just changed.
        if id == (selectedModel?.id ?? -1) || selectedModelId == nil {
            await predict()
        }
    }

    /// Delete the model row. Confirmed in the UI because it is irreversible —
    /// but it destroys no photos, and the dialog says so.
    func deleteModel(_ id: Int) async {
        guard busyModelId == nil else { return }
        busyModelId = id
        defer { busyModelId = nil }
        modelFault = nil
        modelErrorText = nil
        modelOp = .delete
        do {
            _ = try await api.deleteStyleModel(id)
        } catch let error as APIError {
            // The dialog stays open with the refusal on it: closing it would
            // leave the user guessing whether the model is gone.
            modelFault = fault(from: error)
            modelErrorText = error.description
            await loadModels()
            return
        } catch {
            modelErrorText = String(describing: error)
            await loadModels()
            return
        }
        pendingDelete = nil
        // Whether the preview on screen came from the model just deleted.
        let wasPredicting = id == prediction?.model?.id
        await loadModels()
        if wasPredicting || selectedModelId == nil { await predict() }
    }

    /// Choose which model the preview and the write use. Re-asks the engine:
    /// a different model is different numbers, never a re-filter of these.
    func selectModel(_ id: Int?) async {
        guard id != selectedModelId else { return }
        selectedModelId = id
        // Family numbers are relative to the history the model clusters, so a
        // family pinned under one model would mean a different look under
        // another. Back to the engine's suggestion.
        familyOverride = nil
        await predict()
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
            // picks, which is the set a user is about to develop. modelId
            // omitted (nil) means the active model — the engine's own default,
            // resolved server-side so both clients resolve it identically.
            let r = try await api.stylePredict(
                shootId: shootId, family: familyOverride, photoIds: nil,
                modelId: selectedModelId)
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
            // The same model the preview used: the engine echoes it back, so
            // the result names the source of the values it wrote.
            writeResult = try await api.styleExportDevelop(
                shootId: shootId, family: family, photoIds: ids,
                modelId: selectedModelId)
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
