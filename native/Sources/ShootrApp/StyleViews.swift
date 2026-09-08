import AppKit
import SwiftUI

// MARK: - Style learning screens (design 08 §7a, 12 §4a)
//
// Two sections on one screen, same as the web client: the look families
// discovered in the user's edit history, and the prediction preview for the
// open shoot. Everything shown is an engine payload — traits, medians,
// params, confidence, neighbour ids, guardrails, abstain reasons. The client
// renders them and nothing more (rule 6).
//
// The copy is deliberately the SAME STRINGS as the web client
// (web/src/style.ts, StyleView.tsx, LookFamilies.tsx, StylePredictPanel.tsx,
// StyleWriteDialog.tsx). Doc 12 §4a: native must not diverge in wording or
// in which guardrails are surfaced. Where a sentence here reads oddly for
// native, the fix is to change it in both clients, not to reword one.

enum StyleCopy {
    /// The scope boundary, stated where a user would reasonably expect
    /// brushes to appear (design 08 §1, §7a).
    static let localAdjustments =
        "Global develop sliders only, learned from your own edits. Local "
        + "adjustments — brushes, radial and linear gradients, AI "
        + "subject/sky masks — are never transferred: they are specific to "
        + "one photo's content, and there is no honest way to move them. "
        + "Crop and straighten are yours alone and are never predicted."

    static let previewBanner =
        "Preview only — nothing has been written to your files. These are "
        + "suggested starting points blended from your own past edits; the "
        + "write dialog states the counts before anything touches disk."

    static let familiesHeading =
        "Look families — discovered in your edit history"
    static let predictHeading =
        "Predicted develop settings for this shoot's picks"

    static let noHistoryTitle = "No edit history to learn from yet"
    static let noHistoryBody =
        "Style learning is built entirely from your own past edits — it "
        + "never invents a look. Import a Lightroom Classic catalog (or a "
        + "folder with XMP sidecars carrying develop settings) so the engine "
        + "has edited photos to cluster and copy from."
    static let noHistoryAnalyzed =
        "The imported photos also need to have been analyzed: similarity "
        + "comes from the scene embedding, so an unanalyzed edit is "
        + "invisible to the predictor."

    static let familiesFailed = "The engine could not load look families."
    static let noFamilies =
        "The engine found no look families in the imported history."
    static let clustering = "Clustering your edits…"
    static let noSamples =
        "No sample thumbnails — these edited photos are not in a scanned "
        + "library."
    static let noMedian = "— no median values reported for this family"
    static let usedByPreview = "used by the preview below"
    static let medianHeading = "Median edit"

    // The per-parameter opt-out lives in the engine (design 08 §6/§7a), so
    // these sentences are statements about the user's files, not about this
    // window. Same strings as web/src/components/StylePredictPanel.tsx, with
    // "the web client" where that one says "the native client".
    static let paramsHeading =
        "Parameters — which ones Shootr is allowed to write"
    static let paramsCaveat =
        "Unchecked parameters are never written to your files. The engine "
        + "stores this choice and applies it everywhere — this preview, the "
        + "write, and the web client alike. Values it predicted for an "
        + "excluded parameter are still shown below, struck through, so you "
        + "can see what you turned down rather than losing sight of it."
    static let paramsSaving = "Saving to the engine and re-predicting…"
    static let notWrittenTag = "not written"

    /// A parameter the engine returned but does not list as modelable: shown,
    /// and shown as unswitchable, rather than missing from the panel.
    static func nonModelableHelp(_ name: String) -> String {
        "\(name) — the engine returned this but does not list it as "
        + "modelable, so it cannot be excluded"
    }

    /// Engine error codes from the preferences endpoint → human copy. Mirrors
    /// `prefErrorCopy` in `web/src/style.ts`.
    static func prefErrorCopy(_ code: String?, _ message: String) -> String {
        if code == "unknown_param" {
            return "The engine does not model that parameter, so it cannot be "
                + "excluded. Nothing was changed — reload the screen to pick "
                + "up the engine's current parameter list."
        }
        return "The engine rejected the change (\(code ?? "error")): "
            + "\(message). Nothing was changed."
    }

    /// Parameters we have a MEASURED reason to recommend excluding, with that
    /// reason in the user's own terms. Surfaced as a suggestion, never applied
    /// for them: the exclusion list lives on the server and changes what is
    /// written to their files, so the client proposing it silently would be the
    /// client making the decision (design 08 §7a, design 10 §1).
    ///
    /// k-NN beats the family median on 11 of 12 parameters and loses on this
    /// one (`docs/benchmarks/2026-08-30-style-knn-eval.md`: MAE 0.336 vs 0.283
    /// under leave-one-shot-group-out). Same map as the web client's
    /// `SUGGESTED_EXCLUSIONS`.
    static let suggestedExclusions: [String: String] = [
        "ColorGradeMidtoneHue":
            "Measured on your own edits: the family's median hue beats the "
            + "per-photo prediction here (MAE 0.283 vs 0.336) — the only "
            + "parameter of 12 where it does. Excluding it means Shootr "
            + "leaves midtone hue to you.",
    ]

    static func suggestionTitle(_ name: String) -> String {
        "Suggested: don't write \(StyleParams.label(name))."
    }
    static let suggestionUnchanged =
        "Nothing has been changed — this parameter is currently being written."
    static func suggestionButton(_ name: String) -> String {
        "Exclude \(StyleParams.label(name))"
    }

    static let excludedRowHeading =
        "excluded by you — predicted, not written:"

    /// The preview's tally line. Counts of engine verdicts only — and the
    /// exclusion count, because "how many you turned off" belongs next to
    /// them.
    static func counts(predicted: Int, abstaining: Int, previewed: Int,
                       excluded: Int) -> String {
        var s = "\(predicted) predicted · \(abstaining) abstaining · "
            + "\(previewed) previewed"
        if excluded > 0 {
            s += " · " + plural(excluded, "parameter") + " you excluded"
        }
        return s
    }

    static func excludedChipHelp(_ name: String, _ value: Double) -> String {
        "\(name) — you excluded this parameter; the engine predicted "
        + StyleParams.format(name, value) + StyleParams.unit(name)
        + " and will not write it"
    }

    static let abstainBadge = "no confident prediction — needs manual edit"
    static let nothingWritten = "Nothing will be written for this photo."
    static let noPicks = "The selection's picks contain no photos to predict "
        + "for."
    static let previewFailed = "The engine could not build a preview."
    static let nothingToWrite =
        "Nothing to write — the engine abstained on every photo"
    static let reviewThenConfirm = "Review the counts, then confirm"

    static let conflictsWarning =
        "Conflicts are only known once the write runs: a sidecar that "
        + "already holds your own develop settings is skipped and listed "
        + "afterwards. There is no override — not a checkbox we hid, the "
        + "engine has no such parameter."
    static let writeScope =
        "Global sliders only. Brushes, radial and linear gradients, and AI "
        + "subject/sky masks are never predicted and never written. Crop and "
        + "straighten are left alone too."

    /// Same sentence the select-export dialog ends with (design 07 §3.1).
    static let readMetadataCaveat =
        "In Lightroom: select the photos, then Metadata → Read Metadata "
        + "from Files. Note: that step overwrites catalog metadata from the "
        + "files — LrC's behavior, not ours."

    /// Engine abstention reason → human copy. A photo below the confidence
    /// gate must read as "no confident prediction", never as an empty
    /// parameter list that could pass for "no changes needed". Unknown
    /// reasons are surfaced verbatim rather than swallowed.
    static func abstainCopy(_ reason: String?) -> String {
        switch reason {
        case "low_confidence":
            return "The nearest edits in your history disagree too much, or "
                + "aren't similar enough — below the engine's confidence "
                + "gate."
        case "no_similar_history":
            return "Nothing in this look family looks like this photo, so "
                + "there is nothing honest to copy from."
        case "family_too_small":
            return "This look family has too few edited photos to predict "
                + "from."
        case "not_analyzed":
            return "This photo has no scene embedding yet — analyze the "
                + "shoot before predicting."
        case "model_abstained":
            // A fitted model with nothing to give for this photo (design 08
            // §7b). Same sentence as the web client's ABSTAIN_COPY.
            return "The model returned no value for this photo. Nothing will "
                + "be written for it."
        default:
            return "The engine abstained (reason: "
                + (reason ?? "unspecified") + ")."
        }
    }

    /// The abstention as a prediction row states it: the engine's reason, then
    /// what happens. `model_abstained`'s own copy already ends with that, so it
    /// is not said twice.
    static func abstainLine(_ reason: String?) -> String {
        reason == "model_abstained"
            ? abstainCopy(reason)
            : abstainCopy(reason) + " " + nothingWritten
    }

    static func predictErrorCopy(_ code: String?) -> String {
        switch code {
        case "no_selection":
            return "This shoot has no cull selection yet. Run Analyze & cull "
                + "first — the preview covers the selection's picks."
        case "not_analyzed":
            return "These photos have no scene embeddings yet. Analyze the "
                + "shoot first; similarity is what the prediction is built "
                + "on."
        case "insufficient_history":
            return "Not enough imported edit history to predict from — "
                + "import a Lightroom catalog with your edits."
        case "model_not_trained":
            return "That style model has not been learned yet, so it has "
                + "nothing to predict with. Learn it in Style models above, or "
                + "choose another model."
        case "file_missing":
            return "The engine has no such style model — it may have been "
                + "deleted in another window. Choose a model again."
        default:
            return previewFailed
        }
    }

    static func plural(_ n: Int, _ word: String, _ plural: String? = nil)
        -> String {
        n == 1 ? "\(n) \(word)" : "\(n) \(plural ?? word + "s")"
    }

    /// What the write leaves out, named — so the dialog states the whole of
    /// what it is about to do, not just the part that lands. `withheld` is how
    /// many previewed photos actually had a value taken out: the exclusion and
    /// its effect are separate facts.
    static func excludedNotWritten(_ excluded: [String],
                                   withheld: Int) -> String {
        let names = excluded.map(StyleParams.label).joined(separator: ", ")
        let one = excluded.count == 1
        var s = plural(excluded.count, "parameter") + " you excluded "
            + "(\(names)) " + (one ? "is" : "are") + " not written. The engine "
            + "leaves " + (one ? "it" : "them")
            + " out of every sidecar on this run"
        if withheld > 0 {
            s += " — \(withheld) of these photos had a predicted value for "
                + (one ? "it" : "one of them")
                + ", shown struck through in the preview"
        }
        return s + ". Those sliders stay as they are in Lightroom, yours to "
            + "set."
    }

    /// The engine's echo after the write — the scope confirmed, not assumed.
    static func excludedLeftOut(_ excluded: [String]) -> String {
        let names = excluded.map(StyleParams.label).joined(separator: ", ")
        return "Left out, as you asked: \(names). No value for "
            + (excluded.count == 1 ? "it" : "them")
            + " was written to any of these files."
    }

    /// Every predicted parameter for a photo is excluded. Not an abstention:
    /// the engine had numbers, and the user said no to all of them.
    static func allExcluded(_ n: Int) -> String {
        plural(n, "predicted parameter") + ", all of them ones you excluded — "
        + "nothing from this prediction will be written."
    }

    // MARK: - Style models (design 08 §7b)
    //
    // Every string in this section that the web client also shows is copied
    // VERBATIM from `web/src/style.ts`, `CreateStyleModelForm.tsx`,
    // `StyleModelCompare.tsx` and `DeleteStyleModelDialog.tsx`. The comparison
    // copy especially: two clients describing the same measurement differently
    // are two clients the user has to reconcile before trusting either.
    //
    // The model list rows and the per-row provenance line are native-first
    // (web has not written that surface yet). They are worded in the same
    // vocabulary so the web copy can adopt them unchanged.

    /// Method id → the name to show. Unknown methods fall through as
    /// themselves, so a method the engine gains (design 08 §7b lists `gbt` as
    /// a candidate) appears rather than vanishing from the picker.
    static let methodTitles: [String: String] = [
        "knn": "k-NN — nearest edits in your history",
        "ridge": "Ridge regression — fitted to your history",
        "gbt": "Gradient-boosted trees — fitted to your history",
    ]

    static func methodTitle(_ method: String) -> String {
        methodTitles[method] ?? method
    }

    /// The trade-off between methods, stated rather than hidden: it is the
    /// reason there is a choice here at all. One string, so the web and native
    /// clients say the same thing.
    static let methodTradeoff =
        "The trade-off, plainly: a method that retrieves can show you the "
        + "photos a prediction came from; a method that fits cannot — it can "
        + "only say how much history it was fitted from. Which one is more "
        + "accurate on your own edits is measured, not assumed — learn both "
        + "and compare them."

    /// `fits` → what that means for the user, in facts about behaviour.
    static func methodFitsCopy(_ fits: Bool) -> String {
        fits
            ? "Fits coefficients to your history when you learn the model. "
                + "Newly imported edits do not change its predictions until "
                + "you relearn it."
            : "Fits nothing in advance: each prediction is blended from the "
                + "nearest edits in your history at the moment it is made, so "
                + "newly imported edits count without a relearn. The recorded "
                + "metrics still date from the last learn."
    }

    /// `explains_by_neighbours` → what a prediction from it can tell you.
    /// §7a's inspectability requirement is not waived by accuracy, so a fitted
    /// method's limit is named up front, before the model is created.
    static func methodExplainsCopy(_ explains: Bool) -> String {
        explains
            ? "Every prediction names the photos it was copied from — “edited "
                + "like these five”, with thumbnails."
            : "Predictions cannot name the photos behind a value. Each one "
                + "reports only that it was fitted, and from how many edited "
                + "photos."
    }

    /// How the engine produced the comparison numbers. Not a footnote: it
    /// changes what they mean (design 08 §7b).
    static func heldOutCopy(_ heldOutBy: String?) -> String {
        if heldOutBy == "shot_group" {
            return "Measured on your own edits, held out by shot group: whole "
                + "bursts were kept out of the history the model learned "
                + "from, so a near-duplicate sibling could not hand it the "
                + "answer."
        }
        if heldOutBy == "photo" {
            return "Measured on your own edits, held out photo by photo: "
                + "burst siblings can land on both sides of the split, and a "
                + "near-duplicate sibling in the history flatters retrieval — "
                + "read these numbers as optimistic."
        }
        return "Measured on your own edits, held out by "
            + (heldOutBy ?? "an unreported split") + "."
    }

    /// Which operation a refusal came from. `create` and `relearn` differ in
    /// one fact worth stating: a failed create still leaves the model row
    /// behind, so the user's choice is not silently discarded.
    enum ModelOp { case create, relearn, activate, delete }

    /// Engine error codes from the model endpoints → human copy.
    static func modelErrorCopy(_ code: String?, _ message: String,
                               _ op: ModelOp) -> String {
        if code == "unknown_method" {
            return "The engine does not offer that method (\(message)). "
                + "Nothing was created — reload to pick up the engine's "
                + "current method list."
        }
        if code == "insufficient_history" {
            let tail = op == .create
                ? "The model was created anyway and is listed as not learned, "
                    + "so your choice is not lost: import or analyze those "
                    + "edits, then Relearn it."
                : "The model is unchanged and keeps whatever it last learned, "
                    + "if anything. Import or analyze those edits, then "
                    + "Relearn."
            return "Not enough learnable history in the chosen libraries. The "
                + "engine needs edited photos that are both imported (a "
                + "Lightroom Classic catalog, or XMP sidecars carrying develop "
                + "settings) and analyzed — similarity comes from the scene "
                + "embedding, so an unanalyzed edit is invisible to it. "
                + "\(tail) Engine: \(message)"
        }
        // Everything else, including the engine's 409 `model_not_trained` on
        // activate, carries its own explanatory sentence — relayed rather than
        // paraphrased into a second, drifting version of it.
        return "The engine rejected this (\(code ?? "error")): \(message)."
    }

    /// A model's scope in the user's terms. An empty list means every library,
    /// which is a deliberate answer and is worded as one rather than as
    /// "none". A library since removed is named as missing instead of being
    /// dropped — the model was learned from it either way.
    static let scopeAll = "all libraries"
    static func missingLibrary(_ id: Int) -> String {
        "library \(id) (no longer in Shootr)"
    }

    /// Method knob → display. A null knob is the engine choosing the value
    /// while it learns (ridge's λ by cross-validation), which is not the same
    /// as "unset". Keys are sorted because Swift dictionaries carry no JSON
    /// order; the web client shows them in the engine's order.
    static func formatModelParams(_ params: [String: StyleParamValue])
        -> String {
        params.keys.sorted().map { key in
            let v = params[key] ?? .null
            return "\(key) "
                + (v == .null ? "chosen while learning" : v.display)
        }.joined(separator: " · ")
    }

    /// A measured ERROR (mean absolute error), so unsigned: it is a distance,
    /// and a "+" in front of it would suggest a direction it does not have.
    /// Formatting only — the number itself is the engine's.
    static func formatError(_ name: String, _ value: Double) -> String {
        String(format: name == "Exposure2012" ? "%.3f" : "%.2f", value)
    }

    // MARK: the model list (web: StyleModelsPanel.tsx)

    static let modelsHeading = "Style models"
    static let modelsIntro =
        "A model is yours: you name it, choose how it learns, and choose which "
        + "libraries it learns from. Nothing is learned when you import a "
        + "catalog, and no method is picked for you."
    static let modelsFailed = "The engine could not list your style models."
    static let modelsLoading = "Loading models…"
    /// Not an empty list dressed up as a problem: the feature works without a
    /// model, and the engine says exactly what it falls back to.
    static let noModelsTitle = "No style models yet"
    static let noModelsBody =
        "Predictions still work: with no model, the engine uses its built-in "
        + "default — nearest edits across all your imported history. Creating "
        + "a model turns that into a choice you made, on the libraries you "
        + "picked, with metrics measured for it so it can be compared against "
        + "another."

    static let activeBadge = "active — predicts unless you choose another"
    /// Created but never learned. Distinct from "learned and bad".
    static let notLearnedBadge = "not learned yet"

    static let rowLearnsFrom = "Learns from"
    static let rowHistoryUsed = "Edit history used"
    static let rowProcessVersion = "Process version"
    static let rowLearned = "Learned"
    static let rowKnobs = "Knobs"
    static let rowMeasured = "Measured"

    static func historyUsedValue(_ n: Int, trained: Bool) -> String {
        trained ? plural(n, "edited photo") : "— nothing learned yet"
    }
    static func processVersionValue(_ pv: String?) -> String {
        guard let pv else { return "—" }
        return "\(pv) — the single version its history was narrowed to"
    }
    /// The engine's own timestamp, rendered as given.
    static func learnedAtValue(_ at: String?) -> String { at ?? "never" }
    static func measuredValue(_ wins: Int?, _ scored: Int?,
                              _ coverage: Double?) -> String {
        var s = "beat the family median on \(wins ?? 0) of "
            + "\(scored.map(String.init) ?? "—") parameters"
        if let coverage {
            s += " · predicted for \(Int((coverage * 100).rounded()))% of "
                + "held-out photos"
        }
        return s
    }

    static let modelsActivate = "Activate"
    static let modelsActivating = "Activating…"
    static let modelsRelearn = "Relearn"
    static let modelsLearnNow = "Learn now"
    static let modelsLearning = "Learning…"
    static let modelsDelete = "Delete…"
    static let modelsCreate = "Learn a model…"
    static let modelsCompare = "Compare"
    static let activateHelpUntrained =
        "Learn this model first — an unlearned model cannot predict"
    static let activateHelp =
        "Make this the model that predicts by default, in both clients"
    static let relearnHelp =
        "Re-run this model against your history as it stands now"
    static let relearnNote =
        "Relearn is how new shoots take effect — the engine never retrains on "
        + "its own."

    // MARK: choosing a model for this shoot's preview (web: StylePredictPanel)

    static let modelPickerLabel = "Model"
    static let modelPickerActive = "Active model — the engine's choice"
    /// An unlearned model is listed but not selectable: it exists, and hiding
    /// it would make the list disagree with the manager above.
    static func modelOption(_ name: String, _ method: String, active: Bool,
                            trained: Bool) -> String {
        "\(name) — \(method)" + (active ? " (active)" : "")
        + (trained ? "" : " — not learned yet")
    }

    /// The provenance block above the preview rows: which model ran, learned
    /// when, from how much — and, for a fitted method, what its rows cannot
    /// say. Same sentences as the web client's `ModelProvenance`.
    static func noModelProvenance(_ historyUsed: Int?) -> String {
        "No style model — engine default. These predictions come from the "
        + "engine's built-in fallback: nearest edits across all your imported "
        + "history"
        + (historyUsed.map { " (\(plural($0, "edited photo")))" } ?? "")
        + ". It works, but nobody chose it. Create a model above to fix the "
        + "method and the libraries deliberately, and to get metrics you can "
        + "compare."
    }

    static func modelProvenance(_ model: StyleModelInfo,
                                historyUsed: Int?) -> String {
        var s = "Predicted by \(model.name)"
            + (model.isActive ? " (active)" : "")
            + " — \(methodTitle(model.method)). Learned "
            + learnedAtValue(model.trainedAt) + " from "
            + plural(model.historyN, "edited photo")
        if let pv = model.processVersion {
            s += ", Process Version \(pv)"
        }
        if let used = historyUsed, used != model.historyN {
            s += ". Its libraries now hold \(used) edited photos — relearn to "
                + "measure against those"
        }
        return s + "."
    }

    static let fittedModelNote =
        "This model was fitted, so no prediction below can name the photos "
        + "behind a value: each one reports how much history it was fitted "
        + "from instead. It also reports no confidence number — the confidence "
        + "gate is a property of retrieval, and this method has none, so rows "
        + "show no confidence rather than a made-up one. The §6 guardrails "
        + "still apply: values are clamped to the range seen in your history."

    /// A model scoped to some libraries clusters its own history, so its family
    /// numbering need not match the global list above.
    static let scopedFamiliesNote =
        "Family numbers here come from clustering this model's own libraries, "
        + "so they need not line up with the family list above, which clusters "
        + "all imported history."

    /// True of the fitted path only: the engine drops excluded parameters
    /// before predicting them, so there is no withheld number to strike
    /// through. Better said than left as a puzzle.
    static let fittedExclusionNote =
        "With a fitted model the engine leaves excluded parameters out before "
        + "it predicts them, so there is no withheld value to show: they are "
        + "simply absent below, not struck through."
    // MARK: create form (web: CreateStyleModelForm.tsx)

    static let createHeading = "Learn a style model"
    static func methodsFailed(_ code: String?, _ message: String) -> String {
        "The engine could not list its methods: \(code ?? "error") — \(message)"
    }
    static let nameLabel = "Name"
    static let namePlaceholder = "Weddings 2024–26"
    static let nameHelp =
        "Yours to label. Style drifts over years and genres, so a model is "
        + "worth naming for the work it came from."
    static let methodLabel = "Method"
    static func engineDefaults(_ params: String) -> String {
        "engine defaults: \(params)"
    }
    static let librariesLabel = "Learn from"
    static let librariesHelp =
        "Which libraries the edit history comes from. Leave everything "
        + "unchecked to use all of them. Whatever the scope, the engine "
        + "narrows the history to a single Lightroom process version before "
        + "learning and records which — the same slider renders differently "
        + "across versions, so mixing them would describe neither."
    static let librariesLoading = "Loading libraries…"
    static let librariesNone =
        "No libraries yet. A model can still be created with \"all "
        + "libraries\" as its scope, but there is nothing to learn from until "
        + "one is added and analyzed."
    static let libraryOffline = "(offline)"
    static let scopeAllLine = "Scope: all libraries."
    static func scopeSomeLine(_ chosen: Int, _ total: Int) -> String {
        "Scope: \(chosen) of \(total) libraries."
    }

    /// Stated before the model exists, not discovered later in the preview.
    static func givesUpNeighbours(_ method: String) -> String {
        "\(methodTitle(method)) gives up the neighbour explanation. "
        + "Predictions from it will say they were fitted, and from how many "
        + "edited photos, but not which photos a value came from. The "
        + "guardrails are unchanged — values are still clamped to the range "
        + "seen in your history, and nothing overwrites your own develop "
        + "settings."
    }

    static let createButton = "Create and learn"
    static let createBusy = "Learning…"
    static let createNoMethod =
        "Pick a method — the engine does not choose one for you"
    static let createHelp = "Creates the model and learns it now"

    // MARK: compare (web: StyleModelCompare.tsx)

    static let compareHeading = "Compare models"
    static let compareNothing =
        "No learned model has metrics to compare yet. Learn a model — the "
        + "engine measures it against your own edits as part of learning it."
    static let compareIntro =
        "Each column is what the engine's evaluation harness measured for that "
        + "model, on your own edits. Mean absolute error, in each parameter's "
        + "own units — lower is closer to what you actually did. Shootr shows "
        + "the engine's numbers and its own count of parameters where the "
        + "model beat the family median; it does not add a score of its own or "
        + "name a winner."
    static func mixedSplits(_ splits: [String]) -> String {
        "These models were not held out the same way ("
        + splits.joined(separator: ", ") + "), so their errors are not "
        + "directly comparable. Relearn them so both use the same split "
        + "before reading one against the other."
    }
    static let paramColumn = "Parameter"
    static let rowHistoryN = "Edited photos measured on"
    static let rowFamilies = "Look families"
    static let rowCoverage = "Coverage (predicted, not abstained)"
    static let rowBeatsMedian = "Beat the family median on"
    static let rowHeldOutBy = "Held out by"
    static let rowLambda = "λ used"
    static let heldOutNotReported = "not reported"
    static let perParamHeading =
        "Per parameter — model error vs. family-median baseline"
    static let notScored = "not scored for this model"
    static func medianCell(_ text: String) -> String { "median \(text)" }
    static func nCell(_ n: Int) -> String { "n \(n)" }
    static func beatsMedianCell(_ wins: Int?, _ scored: Int?) -> String {
        guard let wins else { return "—" }
        return "\(wins) of \(scored.map(String.init) ?? "?") parameters"
    }
    /// The engine's fraction, shown as a percentage too — the same number in
    /// different units, not a derived one.
    static func coverageCell(_ coverage: Double?) -> String {
        guard let coverage else { return "—" }
        return "\(Int((coverage * 100).rounded()))% (\(coverage))"
    }
    static func unmeasuredNote(_ names: [String]) -> String {
        "Not in this comparison, because the engine has no metrics for "
        + (names.count == 1 ? "it" : "them") + ": "
        + names.joined(separator: ", ") + ". Relearn to measure."
    }
    static let baselineNoValue =
        "the family median had no value to score here"

    // MARK: delete (web: DeleteStyleModelDialog.tsx)

    static let deleteHeading = "Delete this style model?"
    static func deleteSubject(_ name: String, _ method: String,
                              active: Bool) -> String {
        "\(name) — \(method)" + (active ? " (currently active)" : "")
    }
    static let deleteBody =
        "Only the model is deleted: its name, its method, and what it learned. "
        + "No photo, sidecar or edit of yours is touched, and the edit history "
        + "it learned from is untouched — you can learn the same model again."
    static func deleteSidecars(active: Bool) -> String {
        "Develop settings already written to XMP sidecars stay as they are on "
        + "disk."
        + (active
           ? " This model is active, so until you activate another one "
             + "predictions fall back to the engine's built-in default."
           : "")
    }
    static let deleteButton = "Delete model"
    static let deleteBusy = "Deleting…"

    // MARK: prediction provenance (§7a: a prediction must say where it's from)

    static let provenanceHeading = "Where this came from"
    static func fittedFrom(_ n: Int) -> String {
        "Fitted from " + plural(n, "edited photo") + " of yours."
    }
    static let fittedNoNeighbours =
        "No neighbour photos: a fitted model cannot point at the photos a "
        + "value came from. This is the whole of what it can say about its "
        + "source."
    /// Where a confidence figure would go on a fitted row. Naming the kind of
    /// prediction is honest; an empty gap or a made-up 0 is not.
    static let fittedTag = "fitted prediction"

    /// The write dialog names its source before and after: which predictor's
    /// values are about to land in the user's files, and which the engine says
    /// produced the ones that did (web: StyleWriteDialog.tsx).
    static func writeFromModel(_ model: StyleModelInfo?) -> String {
        guard let model else {
            return "From the engine's built-in default (nearest edits across "
                + "all imported history) — no style model was chosen."
        }
        return "From your model \(model.name) — "
            + "\(methodTitle(model.method)), learned "
            + learnedAtValue(model.trainedAt) + " from "
            + plural(model.historyN, "edited photo") + "."
    }

    static func wroteSidecars(_ n: Int, _ model: StyleModelInfo?) -> String {
        "Wrote " + plural(n, "sidecar")
        + (model.map { " from \($0.name) (\($0.method))." }
           ?? " from the engine's built-in default predictor.")
    }
    static let noParamsReturned =
        "The model returned no parameter values for this photo, so nothing "
        + "will be written for it. That is not the same as \"this photo needs "
        + "no edit\"."
}

// MARK: - Sheet shell

struct StyleSheet: View {
    let shoot: Shoot
    @State private var model = StyleModel()
    @Environment(\.dismiss) private var dismiss

    /// A 409 is a state of the user's data, not a failure to retry: there is
    /// nothing to learn from until a catalog is imported, so the whole screen
    /// becomes that explanation.
    private var noHistory: Bool {
        model.familiesFault?.code == "insufficient_history"
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Theme.hairline)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        Text(StyleCopy.localAdjustments)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)

                        // The models section stays visible with no history:
                        // creating a model is how the user narrows the scope
                        // that has none, and a screen that hid it would leave
                        // them nothing to do but re-import.
                        StyleModelsPanel(model: model)
                        if noHistory {
                            NoHistoryNote(model: model)
                        } else {
                            familiesSection
                            predictSection
                        }
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: model.cursor) {
                    if let p = model.current {
                        withAnimation(.easeOut(duration: 0.15)) {
                            proxy.scrollTo(p.photoId)
                        }
                    }
                }
            }
            Divider().overlay(Theme.hairline)
            footer
        }
        .frame(minWidth: 980, minHeight: 660)
        .background(Theme.bg)
        .background(StyleKeyCatcher(model: model) { dismiss() })
        .task { await model.load(shootId: shoot.id) }
        .sheet(isPresented: $model.showWrite) {
            StyleWriteDialog(model: model)
        }
        .sheet(isPresented: $model.showCreate) {
            CreateStyleModelForm(model: model)
        }
        .sheet(isPresented: $model.showCompare) {
            StyleModelCompareSheet(model: model)
        }
        .sheet(item: $model.pendingDelete) { target in
            DeleteStyleModelDialog(model: model, target: target)
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Text("Style — \(shoot.name)")
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)
                .lineLimit(1)
            Spacer()
            Button("Close") { dismiss() }
                .font(Theme.caption)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Theme.surface)
    }

    private var familiesSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(StyleCopy.familiesHeading)
            if model.loadingFamilies {
                Text(StyleCopy.clustering)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkMuted)
            } else if model.familiesFault != nil
                        || model.familiesErrorText != nil {
                EngineNote(title: StyleCopy.familiesFailed,
                           code: model.familiesFault?.code,
                           message: model.familiesFault?.message
                            ?? model.familiesErrorText ?? "") {
                    Task { await model.loadFamilies() }
                }
            } else if model.families.isEmpty {
                Text(StyleCopy.noFamilies)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkMuted)
            } else {
                ForEach(model.families) { family in
                    FamilyCard(family: family,
                               isUsed: family.id == model.effectiveFamily)
                }
            }
        }
    }

    private var predictSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(StyleCopy.predictHeading)
            if !model.families.isEmpty {
                StylePredictPanel(model: model)
            }
        }
    }

    private var footer: some View {
        HStack(spacing: 10) {
            ForEach(StyleShortcuts.items) { item in
                HStack(spacing: 3) {
                    KeyCap(item.key)
                    Text(item.label)
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                }
            }
            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
        .background(Theme.surface)
    }
}

/// The style screen's keys, in one place so the footer strip and the monitor
/// can't disagree — same discipline as `Shortcuts` for the review screen.
enum StyleShortcuts {
    static let items: [Shortcuts.Item] = [
        Shortcuts.Item("↑ ↓", "move"),
        Shortcuts.Item("J K", "move"),
        Shortcuts.Item("R", "re-predict"),
        // Relearn is L, not R: R re-asks the engine with the model as it is,
        // L re-runs the model against current history. Two different actions,
        // so two keys — and R keeps the meaning it already had.
        Shortcuts.Item("L", "relearn model"),
        Shortcuts.Item("N", "new model…"),
        Shortcuts.Item("C", "compare models…"),
        Shortcuts.Item("W", "write…"),
        Shortcuts.Item("Esc", "close"),
    ]
}

struct NoHistoryNote: View {
    @Bindable var model: StyleModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(StyleCopy.noHistoryTitle)
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)
            Text(StyleCopy.noHistoryBody)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(StyleCopy.noHistoryAnalyzed)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
            // The engine's own sentence carries the current counts, which is
            // what tells the user how far off they are.
            Text("Engine: \(model.familiesFault?.message ?? "")")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button("Try again") {
                    guard let id = model.shootId else { return }
                    Task { await model.load(shootId: id) }
                }
                .font(Theme.caption)
            }
        }
        .padding(14)
        .frame(maxWidth: 640, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
    }
}

/// An engine refusal, with its code and message kept visible.
struct EngineNote: View {
    let title: String
    let code: String?
    let message: String
    var onRetry: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Text("Engine: \(code ?? "error") — \(message)")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
            if let onRetry {
                HStack {
                    Spacer()
                    Button("Try again") { onRetry() }
                        .font(Theme.caption)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: 640, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Style models (design 08 §7b): learn · relearn · compare · choose
//
// The user's objects, with all four operations explicit. Nothing here decides
// anything: the method registry, the metrics, the active model and the scope
// are engine state, and the comparison prints the engine's numbers without
// adding a score, a ranking or a winner of its own (rule 6).

struct StyleModelsPanel: View {
    @Bindable var model: StyleModel

    private var listable: Bool {
        !model.models.isEmpty || model.loadingModels
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                SectionHeader(StyleCopy.modelsHeading)
                Spacer()
                Button(StyleCopy.modelsCompare) { model.showCompare = true }
                    .font(Theme.caption)
                    .disabled(model.models.isEmpty)
                Button(StyleCopy.modelsCreate) { model.beginCreate() }
                    .font(Theme.caption)
            }

            Text(StyleCopy.modelsIntro)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)

            if let error = model.modelsErrorText {
                EngineNote(title: StyleCopy.modelsFailed, code: nil,
                           message: error) {
                    Task { await model.loadModels() }
                }
            }

            // A refused learn / relearn / activate / delete: its own sentence,
            // and what state the model is in afterwards.
            if model.modelFault != nil || model.modelErrorText != nil {
                Text(StyleCopy.modelErrorCopy(
                    model.modelFault?.code,
                    model.modelFault?.message ?? model.modelErrorText ?? "",
                    model.modelOp))
                    .font(Theme.micro)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.surfaceRaised,
                                in: RoundedRectangle(cornerRadius: 5))
                    .overlay(RoundedRectangle(cornerRadius: 5)
                        .stroke(.red.opacity(0.5), lineWidth: 1))
            }

            if model.loadingModels, model.models.isEmpty {
                Text(StyleCopy.modelsLoading)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkMuted)
            } else if !listable, model.modelsErrorText == nil {
                VStack(alignment: .leading, spacing: 4) {
                    Text(StyleCopy.noModelsTitle)
                        .font(Theme.caption)
                        .foregroundStyle(Theme.ink)
                    Text(StyleCopy.noModelsBody)
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
            } else {
                ForEach(model.models) { info in
                    StyleModelRow(
                        model: model, info: info,
                        usedByPreview: model.predictingModel?.id == info.id)
                }
            }
        }
    }
}

/// One model: name, method, scope, how much history it learned from, which
/// process version, when — and what its method can show you. Every field is
/// the engine's; the row adds no verdict about the model. Same fields and the
/// same sentences as the web client's `ModelRow`.
struct StyleModelRow: View {
    @Bindable var model: StyleModel
    let info: StyleModelInfo
    /// The model the preview below actually ran with, straight from the predict
    /// response — so "used by the preview" is the engine's answer, not this
    /// client's guess about how its own picker resolved.
    let usedByPreview: Bool

    private var busy: Bool { model.busyModelId == info.id }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(info.name)
                    .font(Theme.heading)
                    .foregroundStyle(Theme.ink)
                if info.isActive { badge(StyleCopy.activeBadge, Theme.alt) }
                if usedByPreview {
                    badge(StyleCopy.usedByPreview, Theme.inkMuted)
                }
                if !info.trained {
                    badge(StyleCopy.notLearnedBadge, Theme.warning)
                }
                Spacer()
                if busy { ProgressView().controlSize(.mini) }
                Text(StyleCopy.methodTitle(info.method))
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
            }

            Grid(alignment: .topLeading, horizontalSpacing: 10,
                 verticalSpacing: 2) {
                field(StyleCopy.rowLearnsFrom, model.scopeLabel(info))
                field(StyleCopy.rowHistoryUsed,
                      StyleCopy.historyUsedValue(info.historyN,
                                                 trained: info.trained))
                field(StyleCopy.rowProcessVersion,
                      StyleCopy.processVersionValue(info.processVersion))
                field(StyleCopy.rowLearned,
                      StyleCopy.learnedAtValue(info.trainedAt))
                if !info.params.isEmpty {
                    field(StyleCopy.rowKnobs,
                          StyleCopy.formatModelParams(info.params),
                          mono: true)
                }
                // The engine's own tally, printed as it came. Recounting it
                // here would be this client keeping a second opinion about
                // which model is better (rule 6).
                if info.metrics.paramsScored != nil {
                    field(StyleCopy.rowMeasured,
                          StyleCopy.measuredValue(info.metrics.beatsMedianOn,
                                                  info.metrics.paramsScored,
                                                  info.metrics.coverage))
                }
            }

            // §7a's inspectability fact, per model: what a prediction from it
            // will be able to tell the user.
            Text(StyleCopy.methodExplainsCopy(info.explainsByNeighbours))
                .font(Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)

            if info.metrics.heldOutBy != nil {
                Text(StyleCopy.heldOutCopy(info.metrics.heldOutBy))
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 8) {
                Button(busy && model.modelOp == .activate
                       ? StyleCopy.modelsActivating : StyleCopy.modelsActivate) {
                    Task { await model.activate(info.id) }
                }
                .font(Theme.caption)
                .disabled(info.isActive || !info.trained
                          || model.busyModelId != nil)
                .help(info.trained ? StyleCopy.activateHelp
                      : StyleCopy.activateHelpUntrained)

                Button(busy && model.modelOp == .relearn
                       ? StyleCopy.modelsLearning
                       : (info.trained ? StyleCopy.modelsRelearn
                          : StyleCopy.modelsLearnNow)) {
                    Task { await model.relearn(info.id) }
                }
                .font(Theme.caption)
                .disabled(model.busyModelId != nil)
                .help(StyleCopy.relearnHelp)

                Button(StyleCopy.modelsDelete) {
                    // A previous operation's refusal must not appear on the
                    // delete dialog as though it were about the delete.
                    model.modelFault = nil
                    model.modelErrorText = nil
                    model.pendingDelete = info
                }
                .font(Theme.caption)
                .disabled(model.busyModelId != nil)

                Spacer()

                Text(StyleCopy.relearnNote)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 260, alignment: .trailing)
                    .multilineTextAlignment(.trailing)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(info.isActive ? Theme.alt.opacity(0.5) : .clear,
                        lineWidth: 1))
    }

    private func badge(_ text: String, _ tint: Color) -> some View {
        HStack(spacing: 4) {
            StateSwatch(color: tint)
            Text(text)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
        }
        .padding(.horizontal, 7)
        .padding(.vertical, 3)
        .background(Theme.surfaceRaised, in: Capsule())
    }

    private func field(_ label: String, _ value: String,
                       mono: Bool = false) -> some View {
        GridRow {
            Text(label)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .frame(width: 130, alignment: .leading)
            Text(value)
                .font(mono ? Theme.value : Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: - Learn a model (operation 1: create AND learn, one explicit action)

/// Name, method, libraries. No method is preselected — the engine privileges
/// none, and a filled-in radio would be this client recommending one. Each
/// option states the two facts that decide the choice (design 08 §7b): whether
/// it fits, and whether a prediction can name the photos behind it.
struct CreateStyleModelForm: View {
    @Bindable var model: StyleModel
    @Environment(\.dismiss) private var dismiss

    private var chosen: StyleMethod? {
        model.methods.first { $0.method == model.newMethod }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(StyleCopy.createHeading)
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let error = model.modelsErrorText {
                        Text(StyleCopy.methodsFailed(nil, error))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    nameField
                    methodField
                    librariesField
                    if let chosen, !chosen.explainsByNeighbours {
                        // Stated before the model exists, not discovered later
                        // in the preview.
                        Text(StyleCopy.givesUpNeighbours(chosen.method))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Theme.surfaceRaised,
                                        in: RoundedRectangle(cornerRadius: 5))
                            .overlay(RoundedRectangle(cornerRadius: 5)
                                .stroke(Theme.bracket.opacity(0.5),
                                        lineWidth: 1))
                    }
                    if model.createFault != nil
                        || model.createErrorText != nil {
                        Text(StyleCopy.modelErrorCopy(
                            model.createFault?.code,
                            model.createFault?.message
                                ?? model.createErrorText ?? "", .create))
                            .font(Theme.micro)
                            .foregroundStyle(.red)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Theme.surfaceRaised,
                                        in: RoundedRectangle(cornerRadius: 5))
                            .overlay(RoundedRectangle(cornerRadius: 5)
                                .stroke(.red.opacity(0.5), lineWidth: 1))
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
                Button(model.creating ? StyleCopy.createBusy
                       : StyleCopy.createButton) {
                    Task { await model.createModel() }
                }
                .disabled(model.creating
                          || model.newName.trimmingCharacters(
                              in: .whitespacesAndNewlines).isEmpty
                          || model.newMethod == nil)
                .help(model.newMethod == nil ? StyleCopy.createNoMethod
                      : StyleCopy.createHelp)
            }
        }
        .padding(18)
        .frame(width: 620, height: 620)
        .background(Theme.surface)
        .onKeyPress(.escape) { dismiss(); return .handled }
    }

    private var nameField: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(StyleCopy.nameLabel)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
            TextField(StyleCopy.namePlaceholder, text: $model.newName)
                .font(Theme.caption)
            Text(StyleCopy.nameHelp)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var methodField: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(StyleCopy.methodLabel)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
            Text(StyleCopy.methodTradeoff)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(model.methods) { method in
                methodOption(method)
            }
        }
    }

    private func methodOption(_ method: StyleMethod) -> some View {
        let picked = model.newMethod == method.method
        return Button {
            model.newMethod = method.method
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: picked
                          ? "largecircle.fill.circle" : "circle")
                        .font(.system(size: 11))
                        .foregroundStyle(picked ? Theme.alt : Theme.inkMuted)
                    Text(StyleCopy.methodTitle(method.method))
                        .font(Theme.caption)
                        .foregroundStyle(Theme.ink)
                    Text(method.method)
                        .font(Theme.value)
                        .foregroundStyle(Theme.inkMuted)
                }
                Text(StyleCopy.methodFitsCopy(method.fits))
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(StyleCopy.methodExplainsCopy(method.explainsByNeighbours))
                    .font(Theme.micro)
                    .foregroundStyle(method.explainsByNeighbours
                                     ? Theme.inkSecondary : Theme.bracket)
                    .fixedSize(horizontal: false, vertical: true)
                if !method.defaultParams.isEmpty {
                    Text(StyleCopy.engineDefaults(
                        StyleCopy.formatModelParams(method.defaultParams)))
                        .font(Theme.value)
                        .foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(picked ? Theme.surfaceRaised : Theme.surface,
                        in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6)
                .stroke(picked ? Theme.alt.opacity(0.5) : Theme.hairline,
                        lineWidth: 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var librariesField: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(StyleCopy.librariesLabel)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
            Text(StyleCopy.librariesHelp)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if model.loadingModels, model.libraries.isEmpty {
                Text(StyleCopy.librariesLoading)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
            } else if model.libraries.isEmpty {
                Text(StyleCopy.librariesNone)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                ForEach(model.libraries, id: \.id) { library in
                    Toggle(isOn: Binding(
                        get: { model.newLibraryIds.contains(library.id) },
                        set: { on in
                            if on { model.newLibraryIds.insert(library.id) }
                            else { model.newLibraryIds.remove(library.id) }
                        })) {
                        HStack(spacing: 4) {
                            Text(library.rootPath)
                                .foregroundStyle(Theme.inkSecondary)
                            if !library.online {
                                Text(StyleCopy.libraryOffline)
                                    .foregroundStyle(Theme.inkMuted)
                            }
                        }
                        .font(Theme.micro)
                    }
                    .toggleStyle(.checkbox)
                }
                Text(model.newLibraryIds.isEmpty
                     ? StyleCopy.scopeAllLine
                     : StyleCopy.scopeSomeLine(model.newLibraryIds.count,
                                               model.libraries.count))
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
            }
        }
    }
}

// MARK: - Compare (operation 3): the engine's numbers, side by side

/// Models next to each other on the metrics ONE harness measured for each of
/// them. This view deliberately computes nothing: no aggregate, no ranking, no
/// per-parameter winner mark. Those would be the client inventing a verdict on
/// top of the engine's measurements, which is how two frontends start
/// disagreeing about which model is better (rule 6). The only tally shown is
/// `beats_median_on`, which the engine itself counted.
struct StyleModelCompareSheet: View {
    @Bindable var model: StyleModel
    @Environment(\.dismiss) private var dismiss

    private var measured: [StyleModelInfo] { model.measuredModels }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(StyleCopy.compareHeading)
                    .font(Theme.heading)
                    .foregroundStyle(Theme.ink)
                Spacer()
                Button("Close") { dismiss() }
                    .font(Theme.caption)
            }

            if measured.isEmpty {
                Text(StyleCopy.compareNothing)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(StyleCopy.compareIntro)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)

                // Different splits → the columns were not measured the same
                // way. Said out loud, because comparing across splits is the
                // mistake §7b exists to prevent.
                if model.comparedSplits.count > 1 {
                    Text(StyleCopy.mixedSplits(model.comparedSplits))
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Theme.surfaceRaised,
                                    in: RoundedRectangle(cornerRadius: 5))
                        .overlay(RoundedRectangle(cornerRadius: 5)
                            .stroke(Theme.bracket.opacity(0.5), lineWidth: 1))
                }

                ScrollView([.vertical, .horizontal]) {
                    table
                }

                VStack(alignment: .leading, spacing: 3) {
                    ForEach(measured) { m in
                        Text("\(m.name): "
                             + StyleCopy.heldOutCopy(m.metrics.heldOutBy))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            if !model.unmeasuredModels.isEmpty {
                Text(StyleCopy.unmeasuredNote(
                    model.unmeasuredModels.map(\.name)))
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(18)
        .frame(width: 860, height: 660)
        .background(Theme.surface)
        .onKeyPress(.escape) { dismiss(); return .handled }
    }

    private var table: some View {
        Grid(alignment: .topLeading, horizontalSpacing: 16,
             verticalSpacing: 6) {
            GridRow {
                Text(StyleCopy.paramColumn)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .frame(width: 170, alignment: .leading)
                ForEach(measured) { m in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 5) {
                            Text(m.name)
                                .font(Theme.caption)
                                .foregroundStyle(Theme.ink)
                            if m.isActive {
                                Text(StyleCopy.activeBadge)
                                    .font(Theme.micro)
                                    .foregroundStyle(Theme.inkSecondary)
                                    .padding(.horizontal, 5)
                                    .padding(.vertical, 1)
                                    .background(Theme.surfaceRaised,
                                                in: Capsule())
                            }
                        }
                        Text(StyleCopy.methodTitle(m.method))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                        Text(model.scopeLabel(m))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }
                    .frame(width: 190, alignment: .leading)
                }
            }
            Divider().overlay(Theme.hairline).gridCellColumns(
                measured.count + 1)

            // How each column was produced, before any of its numbers.
            provenanceRow(StyleCopy.rowHistoryN) {
                "\($0.metrics.historyN ?? $0.historyN)"
            }
            provenanceRow(StyleCopy.rowFamilies) {
                $0.metrics.families.map(String.init) ?? "—"
            }
            provenanceRow(StyleCopy.rowCoverage) {
                StyleCopy.coverageCell($0.metrics.coverage)
            }
            provenanceRow(StyleCopy.rowBeatsMedian) {
                StyleCopy.beatsMedianCell($0.metrics.beatsMedianOn,
                                          $0.metrics.paramsScored)
            }
            provenanceRow(StyleCopy.rowHeldOutBy) {
                $0.metrics.heldOutBy ?? StyleCopy.heldOutNotReported
            }
            // Only ridge has a λ; "—" is "this method has none", which is not
            // the same as a λ of zero.
            provenanceRow(StyleCopy.rowLambda) {
                $0.metrics.lambda.map {
                    StyleParamValue.double($0).display } ?? "—"
            }

            GridRow {
                Text(StyleCopy.perParamHeading)
                    .font(Theme.micro)
                    .textCase(.uppercase)
                    .foregroundStyle(Theme.inkMuted)
                    .gridCellColumns(measured.count + 1)
            }

            ForEach(model.comparedParamNames, id: \.self) { name in
                GridRow {
                    Text(StyleParams.label(name)
                         + StyleParams.unit(name))
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                        .frame(width: 170, alignment: .leading)
                    ForEach(measured) { m in
                        paramCell(m, name)
                    }
                }
            }
        }
    }

    private func provenanceRow(
        _ label: String, _ cell: @escaping (StyleModelInfo) -> String
    ) -> some View {
        GridRow {
            Text(label)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .frame(width: 170, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(measured) { m in
                Text(cell(m))
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .frame(width: 190, alignment: .leading)
            }
        }
    }

    private func paramCell(_ m: StyleModelInfo,
                           _ name: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            if let row = m.metrics.perParam?[name] {
                Text(StyleCopy.formatError(name, row.mae))
                    .font(Theme.value)
                    .foregroundStyle(Theme.inkSecondary)
                    .help("\(name): model MAE \(row.mae)")
                Text(StyleCopy.medianCell(
                    row.baselineMae.map {
                        StyleCopy.formatError(name, $0) } ?? "—"))
                    .font(Theme.value)
                    .foregroundStyle(Theme.inkMuted)
                    .help(row.baselineMae.map {
                        "family median MAE \($0)" }
                        ?? StyleCopy.baselineNoValue)
                Text(StyleCopy.nCell(row.n))
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
            } else {
                // Not scored for this model — a gap in the measurement, not a
                // zero error (rule 8).
                Text(StyleCopy.notScored)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(width: 190, alignment: .leading)
    }
}

// MARK: - Delete a model (destroys no photos — and says so)

struct DeleteStyleModelDialog: View {
    @Bindable var model: StyleModel
    let target: StyleModelInfo
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(StyleCopy.deleteHeading)
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)

            Text(StyleCopy.deleteSubject(target.name, target.method,
                                         active: target.isActive))
                .font(Theme.caption)
                .foregroundStyle(Theme.inkMuted)

            Text(StyleCopy.deleteBody)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)

            Text(StyleCopy.deleteSidecars(active: target.isActive))
                .font(Theme.caption)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)

            if model.modelFault != nil || model.modelErrorText != nil {
                Text(StyleCopy.modelErrorCopy(
                    model.modelFault?.code,
                    model.modelFault?.message
                        ?? model.modelErrorText ?? "", .delete))
                    .font(Theme.micro)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack {
                Spacer()
                Button("Cancel") {
                    model.pendingDelete = nil
                    dismiss()
                }
                // Never the default action: no Return-key path into deleting
                // something the user built.
                Button(model.busyModelId == target.id
                       ? StyleCopy.deleteBusy : StyleCopy.deleteButton) {
                    Task { await model.deleteModel(target.id) }
                }
                .disabled(model.busyModelId != nil)
            }
        }
        .padding(18)
        .frame(width: 520)
        .background(Theme.surface)
        .onKeyPress(.escape) {
            model.pendingDelete = nil
            dismiss()
            return .handled
        }
    }
}
// MARK: - Screen 1: look families (read-only; discovered, not configured)

struct FamilyCard: View {
    let family: StyleFamily
    /// The family the prediction preview is using, so the user can see which
    /// of their looks is being applied.
    let isUsed: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("Family \(family.id)")
                    .font(Theme.heading)
                    .foregroundStyle(Theme.ink)
                Text(StyleCopy.plural(family.size, "edited photo"))
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkMuted)
                if isUsed {
                    HStack(spacing: 4) {
                        StateSwatch(color: Theme.alt)
                        Text(StyleCopy.usedByPreview)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(Theme.surfaceRaised, in: Capsule())
                }
                Spacer()
                // The engine's trait label, verbatim.
                Text(family.traits)
                    .font(Theme.value)
                    .foregroundStyle(Theme.inkSecondary)
            }

            if family.samplePhotoIds.isEmpty {
                Text(StyleCopy.noSamples)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
            } else {
                HStack(spacing: 6) {
                    ForEach(family.samplePhotoIds, id: \.self) { pid in
                        StyleThumb(photoId: pid, width: 96, height: 64)
                            .help("photo \(pid)")
                    }
                }
            }

            Text(StyleCopy.medianHeading)
                .font(Theme.micro)
                .textCase(.uppercase)
                .foregroundStyle(Theme.inkMuted)
            if family.median.isEmpty {
                // Not "no edits": the engine had no value for any parameter
                // in this family (rule 8 — null is not zero).
                Text(StyleCopy.noMedian)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
            } else {
                ParamChips(params: StyleParams.ordered(
                    Set(family.median.keys)).compactMap { name in
                        family.median[name].map { (name, $0) }
                    })
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(isUsed ? Theme.alt.opacity(0.5) : .clear,
                        lineWidth: 1))
    }
}

// MARK: - Screen 2: predict for a shoot (a preview, presented as one)

struct StylePredictPanel: View {
    @Bindable var model: StyleModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            banner
            controls
            if model.predictFault != nil || model.predictErrorText != nil {
                EngineNote(
                    title: StyleCopy.predictErrorCopy(
                        model.predictFault?.code),
                    code: model.predictFault?.code,
                    message: model.predictFault?.message
                        ?? model.predictErrorText ?? "") {
                    Task { await model.predict() }
                }
            }
            // Waits for the engine's list rather than guessing one: the
            // togglable set IS `modelable_params`, and a click there writes to
            // the user's files.
            if model.prefsLoaded, !model.paramNames.isEmpty { paramsBox }
            if model.prediction != nil && model.predictions.isEmpty {
                Text(StyleCopy.noPicks)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkMuted)
            }
            LazyVStack(alignment: .leading, spacing: 6) {
                ForEach(Array(model.predictions.enumerated()),
                        id: \.element.photoId) { i, p in
                    StylePredictionRow(
                        prediction: p,
                        params: p.params.map(model.orderedParams) ?? [],
                        excluded: p.excluded.map(model.orderedParams) ?? [],
                        isCurrent: i == model.cursor,
                        producedBy: model.predictingModel)
                        .id(p.photoId)
                        .onTapGesture { model.cursor = i }
                }
            }
        }
    }

    /// Unmistakably a preview.
    private var banner: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: "eye")
                .font(.system(size: 11))
                .foregroundStyle(Theme.alt)
            Text(StyleCopy.previewBanner)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 6))
        .overlay(RoundedRectangle(cornerRadius: 6)
            .stroke(Theme.alt.opacity(0.4), lineWidth: 1))
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Choose (design 08 §7b, operation 4). "Active model" is the
            // engine's own answer and is labelled as such — defaulting to a
            // particular model here would be the client holding a second
            // opinion about which one matters. Selecting one sends its id;
            // "active" sends no `model_id` at all.
            HStack(spacing: 8) {
                Picker(StyleCopy.modelPickerLabel, selection: Binding(
                    get: { model.selectedModelId },
                    set: { id in Task { await model.selectModel(id) } })) {
                    Text(StyleCopy.modelPickerActive).tag(Int?.none)
                    ForEach(model.models) { m in
                        Text(StyleCopy.modelOption(m.name, m.method,
                                                   active: m.isActive,
                                                   trained: m.trained))
                            .tag(Int?.some(m.id))
                    }
                }
                .frame(maxWidth: 460)
                if model.predicting {
                    HStack(spacing: 5) {
                        ProgressView().controlSize(.mini)
                        Text("predicting…")
                            .font(Theme.caption)
                            .foregroundStyle(Theme.inkMuted)
                    }
                }
                Spacer()
            }
            // Which model actually produced what is on screen, learned when and
            // from how much — the engine's echo, so a fallback is named as one.
            if model.prediction != nil { provenance }
            HStack(spacing: 8) {
                Picker("Look family", selection: Binding(
                    get: { model.familyOverride },
                    set: { f in Task { await model.setFamily(f) } })) {
                    Text("Auto — let the engine suggest").tag(Int?.none)
                    ForEach(model.families) { f in
                        Text("Family \(f.id) (\(f.size)) — \(f.traits)")
                            .tag(Int?.some(f.id))
                    }
                }
                .frame(maxWidth: 380)
                Spacer()
                Button("Re-predict") { Task { await model.predict() } }
                    .font(Theme.caption)
                Button("Write to XMP…") { model.showWrite = true }
                    .font(Theme.caption)
                    .disabled(model.writeIds.isEmpty)
                    .help(model.writeIds.isEmpty
                          ? StyleCopy.nothingToWrite
                          : StyleCopy.reviewThenConfirm)
            }
            HStack(spacing: 12) {
                if let resolved = model.effectiveFamily {
                    Text("using family \(resolved)"
                         + (model.familyOverride == nil
                            ? " (engine's suggestion)" : "")
                         + (model.prediction.map {
                             " · Process Version \($0.processVersion)" } ?? ""))
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                }
                Spacer()
                if model.prediction != nil {
                    Text(StyleCopy.counts(
                        predicted: model.predicted.count,
                        abstaining: model.abstainingCount,
                        previewed: model.predictions.count,
                        excluded: model.excludedParams.count))
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
        }
    }

    /// Which model produced the preview, in the engine's own terms. A fitted
    /// model gets the extra paragraph: its rows can name no photos and report
    /// no confidence, and that is said once here rather than being discovered
    /// row by row (design 08 §7a/§7b).
    private var provenance: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(model.predictingModel.map {
                StyleCopy.modelProvenance(
                    $0, historyUsed: model.prediction?.history?.used) }
                 ?? StyleCopy.noModelProvenance(
                     model.prediction?.history?.used))
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let used = model.predictingModel,
               !used.explainsByNeighbours {
                Text(StyleCopy.fittedModelNote)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.bracket)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let used = model.predictingModel, !used.libraryIds.isEmpty {
                Text(StyleCopy.scopedFamiliesNote)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 6))
    }

    /// The per-parameter opt-out. Each checkbox is a PUT to the engine and a
    /// re-predict; unchecking one stops that parameter being written by either
    /// client (design 08 §6/§7a).
    private var paramsBox: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(StyleCopy.paramsHeading)
                .font(Theme.micro)
                .textCase(.uppercase)
                .foregroundStyle(Theme.inkMuted)
            Text(StyleCopy.paramsCaveat)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)

            // The fitted path never produces a withheld value to strike
            // through: the engine drops excluded parameters before predicting
            // them. Said, rather than left as a puzzle.
            if let used = model.predictingModel, !used.explainsByNeighbours {
                Text(StyleCopy.fittedExclusionNote)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            FlowLayout(spacing: 10) {
                ForEach(model.paramNames, id: \.self) { name in
                    ParamToggle(model: model, name: name)
                }
            }

            if model.savingPrefs {
                Text(StyleCopy.paramsSaving)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
            }

            // A refused PUT (400 `unknown_param`) or the engine gone on that
            // call: its own sentence, and that nothing was stored.
            if model.prefsFault != nil || model.prefsErrorText != nil {
                Text(StyleCopy.prefErrorCopy(
                    model.prefsFault?.code,
                    model.prefsFault?.message
                        ?? model.prefsErrorText ?? ""))
                    .font(Theme.micro)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Theme.surfaceRaised,
                                in: RoundedRectangle(cornerRadius: 5))
                    .overlay(RoundedRectangle(cornerRadius: 5)
                        .stroke(.red.opacity(0.5), lineWidth: 1))
            }

            ForEach(model.suggestedExclusions, id: \.self) { name in
                suggestion(name)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 6))
    }

    /// A measured suggestion, offered rather than applied: excluding a
    /// parameter changes the user's files, so the reason is stated and the
    /// click is theirs (design 08 §7a).
    private func suggestion(_ name: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(StyleCopy.suggestionTitle(name) + " "
                 + (StyleCopy.suggestedExclusions[name] ?? ""))
                .font(Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(StyleCopy.suggestionUnchanged)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(StyleCopy.suggestionButton(name)) {
                    Task { await model.acceptSuggestion(name) }
                }
                .font(Theme.micro)
                .disabled(model.savingPrefs)
                Spacer()
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surfaceRaised,
                    in: RoundedRectangle(cornerRadius: 5))
        .overlay(RoundedRectangle(cornerRadius: 5)
            .stroke(Theme.alt.opacity(0.4), lineWidth: 1))
    }
}

/// One parameter's checkbox: checked = written. Unchecking it PUTs the engine's
/// exclusion list and re-predicts. A parameter the engine returned but does not
/// list as modelable cannot be excluded (the PUT would 400), so it is shown
/// disabled with that reason rather than left out of the panel.
struct ParamToggle: View {
    @Bindable var model: StyleModel
    let name: String

    var body: some View {
        let off = model.isExcluded(name)
        let togglable = model.isModelable(name)
        Toggle(isOn: Binding(
            get: { !off },
            set: { on in Task { await model.setExcluded(name, !on) } })) {
            HStack(spacing: 4) {
                Text(StyleParams.label(name))
                    .strikethrough(off, color: Theme.inkMuted)
                    .foregroundStyle(off ? Theme.inkMuted
                                     : Theme.inkSecondary)
                if off {
                    Text(StyleCopy.notWrittenTag)
                        .foregroundStyle(Theme.inkMuted)
                }
            }
            .font(Theme.micro)
        }
        .toggleStyle(.checkbox)
        .disabled(!togglable || model.savingPrefs)
        .opacity(togglable ? 1 : 0.6)
        .help(togglable ? name : StyleCopy.nonModelableHelp(name))
    }
}

struct StylePredictionRow: View {
    let prediction: StylePrediction
    /// What will be written, in display order.
    let params: [(String, Double)]
    /// What was predicted and will not be written, with its value — the
    /// engine's `excluded` map (design 08 §7a).
    let excluded: [(String, Double)]
    let isCurrent: Bool
    /// The model the engine says produced this row, nil for its implicit
    /// default. Named per row: "which model was this?" is the first question
    /// once there is more than one (design 08 §7b).
    var producedBy: StyleModelInfo?

    private var neighbors: [Int] { prediction.neighborPhotoIds ?? [] }
    /// A fitted method's provenance: how much history it was fitted from.
    /// Keyed off the engine's field, not off the model's method string.
    private var fittedFrom: Int? { prediction.fittedFromHistoryN }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            StyleThumb(photoId: prediction.photoId, width: 112, height: 80)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("photo \(prediction.photoId)")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkMuted)
                    if prediction.abstained {
                        HStack(spacing: 4) {
                            StateSwatch(color: Theme.warning)
                            Text(StyleCopy.abstainBadge)
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkSecondary)
                        }
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Theme.surfaceRaised, in: Capsule())
                    } else if let confidence = prediction.confidence {
                        // Printed only when the engine reported one. A fitted
                        // method sends null, and "confidence —" or a 0 would
                        // both be inventing a figure it does not publish.
                        Text("confidence "
                             + String(format: "%.2f", confidence))
                            .font(Theme.value)
                            .foregroundStyle(Theme.inkSecondary)
                    } else if fittedFrom != nil {
                        // A fitted method has no retrieval confidence. Say
                        // what it is instead of showing an empty or invented
                        // number.
                        Text(StyleCopy.fittedTag)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }
                }

                if prediction.abstained {
                    // Never a blank parameter list: an abstention is stated,
                    // with its cause, and with what will happen (nothing).
                    Text(StyleCopy.abstainLine(prediction.reason)
                         + (prediction.confidence.map {
                             " (engine confidence "
                             + String(format: "%.2f", $0)
                             + ", below its gate)" } ?? ""))
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else if !params.isEmpty {
                    ParamChips(params: params)
                } else if !excluded.isEmpty {
                    // Predicted, but the user excluded every one of them —
                    // said outright, rather than shown as an empty row that
                    // reads as "no edit". The values themselves are below.
                    Text(StyleCopy.allExcluded(excluded.count))
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    // Not an abstention and not an exclusion: the engine
                    // returned an empty parameter set. Stated, because an
                    // empty row would read as "no changes needed".
                    Text(StyleCopy.noParamsReturned)
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // Excluded by choice: the number the engine had, and the fact
                // that it stays out of the file. Deliberately NOT warning-
                // coloured — an abstention is the engine having nothing to
                // say, this is the user's own decision being honoured.
                if !excluded.isEmpty {
                    Text(StyleCopy.excludedRowHeading)
                        .font(Theme.micro)
                        .textCase(.uppercase)
                        .foregroundStyle(Theme.inkMuted)
                    ParamChips(params: excluded, struck: true)
                }

                // Guardrails the engine applied (design 08 §6). A parameter
                // that was withheld and silently set to 0 would be exactly
                // the opaque number rule 5 forbids, so the engine's sentence
                // travels with it.
                if let damped = prediction.damped, !damped.isEmpty {
                    ForEach(damped.keys.sorted(), id: \.self) { name in
                        HStack(alignment: .firstTextBaseline, spacing: 5) {
                            StateSwatch(color: Theme.warning)
                            Text("\(StyleParams.label(name)) — "
                                 + (damped[name] ?? ""))
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkSecondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // Where the numbers came from. Retrieval names photos; a fitted
            // method reports how much history it was fitted from — and gets
            // that sentence rather than an empty thumbnail strip (§7a, §7b).
            if !neighbors.isEmpty || fittedFrom != nil {
                VStack(alignment: .leading, spacing: 4) {
                    if !neighbors.isEmpty {
                        Text(prediction.abstained
                             ? "Closest \(neighbors.count) in your history — "
                               + "not close enough to copy"
                             : "Edited like these \(neighbors.count)")
                            .font(Theme.micro)
                            .textCase(.uppercase)
                            .foregroundStyle(Theme.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: 300, alignment: .leading)
                        HStack(spacing: 4) {
                            ForEach(neighbors, id: \.self) { pid in
                                StyleThumb(photoId: pid, width: 64, height: 48)
                                    .help("history photo \(pid)")
                            }
                        }
                    } else if let n = fittedFrom {
                        Text(StyleCopy.provenanceHeading)
                            .font(Theme.micro)
                            .textCase(.uppercase)
                            .foregroundStyle(Theme.inkMuted)
                        Text(StyleCopy.fittedFrom(n))
                            .font(Theme.caption)
                            .foregroundStyle(Theme.inkSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(StyleCopy.fittedNoNeighbours)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .frame(maxWidth: 300, alignment: .leading)
            }
        }
        .padding(8)
        .background(isCurrent ? Theme.surfaceRaised : Theme.surface,
                    in: RoundedRectangle(cornerRadius: 6))
        .overlay(
            RoundedRectangle(cornerRadius: 6)
                .stroke(prediction.abstained
                        ? Theme.warning.opacity(0.35) : .clear,
                        lineWidth: 1))
        .contentShape(Rectangle())
    }
}

// MARK: - Write dialog (same shape as the selects export dialog, §11.7)

struct StyleWriteDialog: View {
    @Bindable var model: StyleModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Write predicted develop settings to XMP")
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)

            if let result = model.writeResult {
                resultView(result)
            } else {
                confirmView
            }
        }
        .padding(18)
        .frame(width: 520)
        .background(Theme.surface)
    }

    @ViewBuilder
    private var confirmView: some View {
        VStack(alignment: .leading, spacing: 6) {
            DiffLine(icon: "plus.circle",
                     text: StyleCopy.plural(model.writeIds.count, "photo")
                     + " to write — family \(model.effectiveFamily ?? -1)"
                     + (model.prediction.map {
                         ", Process Version \($0.processVersion)" } ?? ""))
            // Which predictor's values are about to land in the files.
            DiffLine(icon: "wand.and.stars",
                     text: StyleCopy.writeFromModel(model.predictingModel))
            if model.abstainingCount > 0 {
                let n = model.abstainingCount
                DiffLine(icon: "minus.circle",
                         text: "\(n) abstaining: the engine has no confident "
                         + "prediction for \(n == 1 ? "it" : "them"), so "
                         + "nothing at all is written for "
                         + "\(n == 1 ? "it" : "them"). Edit "
                         + "\(n == 1 ? "it" : "those") by hand.")
            }
            // What the write leaves out, named — in the same place the web
            // dialog states it, right after the counts. The list comes from the
            // predict response, so it is the engine's account of this write
            // rather than our recollection of the checkboxes.
            let excluded = model.excludedInPreview
            if !excluded.isEmpty {
                DiffLine(icon: "minus.circle",
                         text: StyleCopy.excludedNotWritten(
                            excluded, withheld: model.withheldCount))
            }
            // Conflicts get no control at all: the engine has no override
            // parameter, so there is no checkbox to offer.
            DiffLine(icon: "exclamationmark.triangle",
                     text: StyleCopy.conflictsWarning, tint: Theme.bracket)
            DiffLine(icon: "info.circle", text: StyleCopy.writeScope)

            if let error = model.writeErrorText {
                Text("Failed: \(error)")
                    .font(Theme.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }

        HStack {
            Spacer()
            Button("Cancel") { close() }
            // Explicit, and never the default action: no Return-key path
            // into writing to the user's files.
            Button(model.writing ? "Writing…"
                   : "Write \(StyleCopy.plural(model.writeIds.count, "sidecar"))") {
                Task { await model.write() }
            }
            .disabled(model.writing || model.writeIds.isEmpty)
        }
    }

    @ViewBuilder
    private func resultView(_ r: StyleWriteResult) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            // The engine names the model it used; relayed so the record of the
            // write says where the values came from.
            Text(StyleCopy.wroteSidecars(r.written.count, r.model))
                .font(Theme.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)

            // The engine reports back which exclusions it honoured; relayed so
            // the write's scope is confirmed rather than assumed.
            if !r.excludedParams.isEmpty {
                Text(StyleCopy.excludedLeftOut(r.excludedParams))
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if !r.abstained.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text(StyleCopy.plural(r.abstained.count, "photo")
                         + " abstained and were left without predicted "
                         + "settings:")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    ForEach(r.abstained.prefix(6), id: \.photoId) { a in
                        Text("photo \(a.photoId) — "
                             + StyleCopy.abstainCopy(a.reason))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if r.abstained.count > 6 {
                        Text("+\(r.abstained.count - 6) more")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }
                }
            }

            if !r.conflicts.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text(StyleCopy.plural(r.conflicts.count, "sidecar")
                         + " already held your own develop settings and were "
                         + "left untouched:")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    ForEach(r.conflicts.prefix(6), id: \.photoId) { c in
                        Text(c.path)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    if r.conflicts.count > 6 {
                        Text("+\(r.conflicts.count - 6) more")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }
                    // Relayed verbatim rather than paraphrased.
                    Text("Engine: \(r.note).")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(8)
                .background(Theme.surfaceRaised,
                            in: RoundedRectangle(cornerRadius: 5))
                .overlay(RoundedRectangle(cornerRadius: 5)
                    .stroke(Theme.bracket.opacity(0.5), lineWidth: 1))
            }

            if !r.written.isEmpty {
                Text(StyleCopy.readMetadataCaveat)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }

        HStack {
            Spacer()
            Button("Done") { close() }
        }
    }

    private func close() {
        model.writeResult = nil
        model.writeErrorText = nil
        model.showWrite = false
        dismiss()
    }
}

// MARK: - Shared bits

/// Engine values as chips: Lightroom's label, then the signed value and its
/// unit, monospaced. Same text the web client puts in its chips.
///
/// `struck` marks a value that exists but is not going into the file (an
/// excluded parameter). The value stays legible on purpose — hiding it would
/// turn "you told us not to write this" back into "we had nothing".
struct ParamChips: View {
    let params: [(String, Double)]
    var struck = false

    var body: some View {
        FlowLayout(spacing: 4) {
            ForEach(params, id: \.0) { name, value in
                Text(StyleParams.chip(name, value))
                    .font(Theme.value)
                    .strikethrough(struck, color: Theme.inkMuted)
                    .foregroundStyle(struck ? Theme.inkMuted
                                     : Theme.inkSecondary)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 2)
                    .background(Theme.surfaceRaised,
                                in: RoundedRectangle(cornerRadius: 3))
                    .help(struck ? StyleCopy.excludedChipHelp(name, value)
                          : name)
            }
        }
    }
}

/// API thumbnail (design 12 §2: grid/filmstrip images come from the API,
/// shared with the web client). Neighbours and family samples belong to
/// other shoots, so the local decode path doesn't apply here.
struct StyleThumb: View {
    let photoId: Int
    let width: CGFloat
    let height: CGFloat

    var body: some View {
        AsyncImage(url: APIClient().thumbURL(photoId: photoId, size: 256)) {
            $0.resizable().aspectRatio(contentMode: .fill)
        } placeholder: {
            Rectangle().fill(Theme.surfaceRaised)
        }
        .frame(width: width, height: height)
        .clipShape(RoundedRectangle(cornerRadius: 4))
    }
}

/// Wrapping row of chips/toggles — the equivalent of the web's flex-wrap.
struct FlowLayout: Layout {
    var spacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews,
                      cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0
        var rowHeight: CGFloat = 0, widest: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0, x + size.width > maxWidth {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            widest = max(widest, x - spacing)
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: maxWidth.isFinite ? min(widest, maxWidth)
                      : widest,
                      height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize,
                       subviews: Subviews, cache: inout ()) {
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0, x + size.width > bounds.width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            view.place(at: CGPoint(x: bounds.minX + x, y: bounds.minY + y),
                       proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

// MARK: - Keyboard (design 12 §4a: same discipline as the review screen)

/// Keys for the style screen via an NSEvent local monitor, for the same
/// reason `KeyCatcher` uses one: first responder moves the moment the user
/// clicks a toggle or a picker, and then `onKeyPress` silently stops firing.
/// Everything passes through while the write dialog is up, so the confirm
/// dialog owns the keyboard.
struct StyleKeyCatcher: NSViewRepresentable {
    let model: StyleModel
    let onClose: () -> Void

    func makeNSView(context: Context) -> NSView {
        context.coordinator.install(model: model, onClose: onClose)
        return NSView()
    }

    func updateNSView(_ view: NSView, context: Context) {
        context.coordinator.model = model
        context.coordinator.onClose = onClose
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    static func dismantleNSView(_ view: NSView, coordinator: Coordinator) {
        coordinator.remove()
    }

    @MainActor
    final class Coordinator {
        var model: StyleModel?
        var onClose: (() -> Void)?
        private var monitor: Any?

        func install(model: StyleModel, onClose: @escaping () -> Void) {
            self.model = model
            self.onClose = onClose
            guard monitor == nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) {
                [weak self] event in
                guard let self, let model = self.model else { return event }
                // Every sheet over this screen owns the keyboard: the write
                // confirm, the create form (it has a text field), the compare
                // sheet and the delete confirm.
                if model.showWrite || model.showCreate || model.showCompare
                    || model.pendingDelete != nil {
                    return event
                }
                if event.window?.firstResponder is NSTextView { return event }
                if event.modifierFlags.intersection(
                    [.command, .option, .control]) != [] { return event }
                return self.handle(event, model: model) ? nil : event
            }
        }

        func remove() {
            if let monitor { NSEvent.removeMonitor(monitor) }
            monitor = nil
        }

        private func handle(_ event: NSEvent, model: StyleModel) -> Bool {
            switch event.keyCode {
            case 53:  // escape
                onClose?()
                return true
            case 125: model.moveCursor(1); return true    // ↓
            case 126: model.moveCursor(-1); return true   // ↑
            case 115: model.cursorToStart(); return true  // home
            case 119: model.cursorToEnd(); return true    // end
            default:
                break
            }
            switch event.charactersIgnoringModifiers ?? "" {
            // J / K are prev / next here too — same direction as the review
            // screen's filmstrip, so the fingers don't relearn.
            case "j": model.moveCursor(-1)
            case "k": model.moveCursor(1)
            case "r": Task { await model.predict() }
            // Relearn what is predicting: the engine re-runs the same model
            // against current history. Distinct from R, which re-asks with the
            // model unchanged.
            case "l":
                if model.selectedModel != nil {
                    Task { await model.relearnSelected() }
                }
            case "n": model.beginCreate()
            case "c":
                if !model.models.isEmpty { model.showCompare = true }
            case "w":
                if !model.writeIds.isEmpty { model.showWrite = true }
            default: return false
            }
            return true
        }
    }
}
