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

    static let filterHeading =
        "Parameters — display filter for this preview only"
    static let filterCaveat =
        "These toggles change what you see here. They do NOT change what "
        + "gets written: the engine's write endpoint applies every predicted "
        + "parameter and has no per-parameter switch yet (design 08 §6). "
        + "The write dialog repeats this and names anything you switched off."

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

    /// The write dialog's warning about the display filter — named
    /// parameters and all, because "some of what you switched off is written
    /// anyway" is not something to leave the user to discover.
    static func hiddenStillWritten(_ hidden: [String]) -> String {
        let names = hidden.map(StyleParams.label).joined(separator: ", ")
        return plural(hidden.count, "parameter")
            + " you switched off in the preview (\(names)) WILL still be "
            + "written. The engine's write endpoint applies every predicted "
            + "parameter and takes no per-parameter switch, so the toggles "
            + "filter what you see, not what lands on disk. Engine-side "
            + "opt-out is still to be built (design 08 §6)."
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
            if !model.paramNames.isEmpty { filterBox }
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
                        shownParams: p.params.map(model.shownParams) ?? [],
                        totalParams: p.params?.count ?? 0,
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
                    Text("\(model.predicted.count) predicted · "
                         + "\(model.abstainingCount) abstaining · "
                         + "\(model.predictions.count) previewed")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
        }
    }

    /// Per-parameter toggles. Labelled for what they actually are: the
    /// engine's write endpoint has no per-parameter switch, so calling these
    /// an opt-out would be a lie about the user's files.
    private var filterBox: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(StyleCopy.filterHeading)
                .font(Theme.micro)
                .textCase(.uppercase)
                .foregroundStyle(Theme.inkMuted)
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.warning)
                Text(StyleCopy.filterCaveat)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            FlowLayout(spacing: 10) {
                ForEach(model.paramNames, id: \.self) { name in
                    Toggle(isOn: Binding(
                        get: { !model.isHidden(name) },
                        set: { _ in model.toggleHidden(name) })) {
                        Text(StyleParams.label(name))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    .toggleStyle(.checkbox)
                    .help(name)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 6))
    }
}

struct StylePredictionRow: View {
    let prediction: StylePrediction
    let shownParams: [(String, Double)]
    let totalParams: Int
    let isCurrent: Bool

    private var neighbors: [Int] { prediction.neighborPhotoIds ?? [] }
    private var hiddenCount: Int { totalParams - shownParams.count }

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
                } else if !shownParams.isEmpty {
                    ParamChips(params: shownParams)
                } else {
                    // Predicted, but every parameter is hidden by the display
                    // filter — say so, rather than showing an empty row that
                    // reads as "no edit".
                    Text(StyleCopy.plural(totalParams,
                                          "predicted parameter")
                         + ", all hidden by your display filter above.")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                }

                if hiddenCount > 0, !shownParams.isEmpty {
                    Text(StyleCopy.plural(hiddenCount,
                                          "more predicted parameter")
                         + " hidden by the display filter (still written).")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
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
            // Conflicts get no control at all: the engine has no override
            // parameter, so there is no checkbox to offer.
            DiffLine(icon: "exclamationmark.triangle",
                     text: StyleCopy.conflictsWarning, tint: Theme.bracket)
            DiffLine(icon: "info.circle", text: StyleCopy.writeScope)

            let hidden = model.hiddenPresentParams
            if !hidden.isEmpty {
                // Honesty over convenience: the toggles filter the preview,
                // and the endpoint takes no parameter list, so pretending the
                // write honours them would be a lie about the user's files.
                Text(StyleCopy.hiddenStillWritten(hidden))
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(8)
                .background(Theme.surfaceRaised,
                            in: RoundedRectangle(cornerRadius: 5))
                .overlay(RoundedRectangle(cornerRadius: 5)
                    .stroke(Theme.warning.opacity(0.5), lineWidth: 1))
            }

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
struct ParamChips: View {
    let params: [(String, Double)]

    var body: some View {
        FlowLayout(spacing: 4) {
            ForEach(params, id: \.0) { name, value in
                Text(StyleParams.chip(name, value))
                    .font(Theme.value)
                    .foregroundStyle(Theme.inkSecondary)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 2)
                    .background(Theme.surfaceRaised,
                                in: RoundedRectangle(cornerRadius: 3))
                    .help(name)
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
