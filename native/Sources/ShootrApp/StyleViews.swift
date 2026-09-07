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
        default:
            return "The engine abstained (reason: "
                + (reason ?? "unspecified") + ")."
        }
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
                        isCurrent: i == model.cursor)
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
                if model.predicting {
                    HStack(spacing: 5) {
                        ProgressView().controlSize(.mini)
                        Text("predicting…")
                            .font(Theme.caption)
                            .foregroundStyle(Theme.inkMuted)
                    }
                }
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

    private var neighbors: [Int] { prediction.neighborPhotoIds ?? [] }

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
                    } else {
                        Text("confidence "
                             + (prediction.confidence.map {
                                 String(format: "%.2f", $0) } ?? "—"))
                            .font(Theme.value)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                }

                if prediction.abstained {
                    // Never a blank parameter list: an abstention is stated,
                    // with its cause, and with what will happen (nothing).
                    Text(StyleCopy.abstainCopy(prediction.reason) + " "
                         + StyleCopy.nothingWritten
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

            if !neighbors.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text(prediction.abstained
                         ? "Closest \(neighbors.count) in your history — not "
                           + "close enough to copy"
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
                }
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
            Text("Wrote \(StyleCopy.plural(r.written.count, "sidecar")).")
                .font(Theme.body)
                .foregroundStyle(Theme.ink)

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
                if model.showWrite { return event }
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
            case "w":
                if !model.writeIds.isEmpty { model.showWrite = true }
            default: return false
            }
            return true
        }
    }
}
