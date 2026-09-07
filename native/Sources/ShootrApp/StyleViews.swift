import AppKit
import SwiftUI

// MARK: - Style learning screens (design 08 §7a, 12 §4a)
//
// Two screens behind one sheet: the discovered look families, and the
// prediction preview for the open shoot. Everything shown here is an engine
// payload — traits, medians, confidence, neighbour ids, abstain reasons. The
// client renders them and nothing more (rule 6). The wording is doc 08 §7a's,
// and the write dialog reuses the select-export dialog's shape and its
// "Read Metadata from Files" caveat verbatim, so the two clients and the two
// export paths can't drift apart in what they promise.

enum StyleCopy {
    static let previewBadge = "PREVIEW — nothing is written yet"

    static let previewExplainer =
        "These are proposals from your own edit history. Nothing is written "
        + "to your files until you press Write… and confirm."

    /// Stated on both screens: a user looking at predicted develop settings
    /// will reasonably wonder about their brushes (design 08 §1, permanent).
    static let localAdjustments =
        "Local adjustments — brushes, radial/linear gradients, AI subject "
        + "and sky masks — are never learned, predicted or written. They are "
        + "out of scope permanently, not a gap to be filled later. Crop and "
        + "straighten are not predicted either."

    static let familiesIntro =
        "Look families are discovered from your edit history by clustering "
        + "your own develop settings — not configured, and not mapped onto "
        + "the four shoot genres. Read-only."

    /// The honest version of §6's per-parameter opt-out. The engine's
    /// export endpoint takes no parameter list, so these toggles cannot
    /// exclude anything from the write, and must not claim to.
    static let filterCaveat =
        "Display filter only — it does NOT change what gets written. The "
        + "engine's write endpoint takes no parameter list, so a write "
        + "sends every parameter it predicted, including the ones hidden "
        + "here. A real per-parameter opt-out is engine-side work that "
        + "isn't built yet (design 08 §6)."

    static let filterHueNote =
        "ColorGradeMidtoneHue starts hidden: measured on the real shoot, "
        + "the family median beats k-NN on that one parameter "
        + "(docs/benchmarks/2026-08-30-style-knn-eval.md). It is the first "
        + "parameter a real opt-out would drop."

    static let conflictsPolicy =
        "A sidecar that already holds your own develop settings is a "
        + "conflict: it is reported and skipped, and your settings are left "
        + "untouched. There is no override — not a checkbox, not a flag. A "
        + "predicted edit is a convenience; your edit is the work."

    /// Same sentence the select-export dialog ends with (design 07 §3.1).
    static let readMetadataCaveat =
        "In Lightroom: select the photos, then Metadata → Read Metadata "
        + "from Files. Note: that step overwrites catalog metadata from the "
        + "files — LrC's behavior, not ours."

    static let abstainHeadline = "no confident prediction — needs manual edit"

    /// The engine's reason in the user's terms. An unrecognized reason
    /// renders as itself rather than vanishing — silence would read as
    /// "nothing to see here", which is the one thing it never means.
    static func abstainReason(_ reason: String?) -> String {
        switch reason {
        case "low_confidence":
            return "the closest edits in this family disagree too much to "
                + "blend into a trustworthy value"
        case "no_similar_history":
            return "nothing in this look family looks like this photo"
        case "family_too_small":
            return "this look family has too few edited photos to predict "
                + "from"
        case "not_analyzed":
            return "this photo has no scene embedding yet — analyze it first"
        case nil:
            return "the engine gave no reason"
        case let other:
            return other ?? ""
        }
    }

    /// Engine faults that have a useful answer, not just a message.
    static func faultTitle(_ fault: EngineFault) -> String {
        switch fault.code {
        case "insufficient_history": return "Not enough edit history yet"
        case "no_selection": return "This shoot has not been culled yet"
        case "not_analyzed": return "These photos have not been analyzed yet"
        case "engine_unreachable": return "Engine not running"
        default: return "Style prediction unavailable"
        }
    }

    static func faultHelp(_ fault: EngineFault) -> String? {
        switch fault.code {
        case "insufficient_history":
            return "Style learning only ever copies you — it needs your own "
                + "edits to learn from. The engine wants at least 10 edited "
                + "photos that have also been analyzed (it matches on scene "
                + "similarity, so an edited photo without a scene embedding "
                + "can't be used).\n\nImport a Lightroom catalog with your "
                + "develop settings, or point Shootr at RAWs with your XMP "
                + "sidecars beside them, then analyze those photos. Look "
                + "families and predictions appear on their own once there "
                + "is enough history — nothing here needs configuring."
        case "no_selection":
            return "Predictions are made for the shoot's picks, so there "
                + "has to be a cull first. Run Analyze & cull on this "
                + "shoot, then come back."
        case "not_analyzed":
            return "Prediction matches photos to your edit history by scene "
                + "similarity, which needs the analysis pass. Run Analyze & "
                + "cull on this shoot first."
        default:
            return nil
        }
    }

    /// Engine values, formatted. Signed because these are deltas onto the
    /// photo's baseline; no unit conversion, no rounding beyond display.
    static func value(_ v: Double) -> String {
        String(format: "%+.2f", v)
    }

    static func confidence(_ v: Double?) -> String {
        v.map { String(format: "%.2f", $0) } ?? "—"
    }
}

// MARK: - Sheet shell

struct StyleSheet: View {
    let shoot: Shoot
    @State private var model = StyleModel()
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Theme.hairline)
            Group {
                switch model.pane {
                case .families: FamiliesPane(model: model)
                case .predict: PredictPane(model: model, shoot: shoot)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            Divider().overlay(Theme.hairline)
            footer
        }
        .frame(minWidth: 1000, minHeight: 660)
        .background(Theme.bg)
        .background(StyleKeyCatcher(model: model) { dismiss() })
        .task { await model.load(shootId: shoot.id) }
        .sheet(isPresented: $model.showWrite) {
            StyleWriteDialog(model: model)
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Text("Style")
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)
            Picker("", selection: $model.pane) {
                Text("Look families").tag(StyleModel.Pane.families)
                Text("Predict for this shoot").tag(StyleModel.Pane.predict)
            }
            .pickerStyle(.segmented)
            .frame(width: 320)
            Text(shoot.name)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkMuted)
                .lineLimit(1)
            Spacer()
            Button("Close") { dismiss() }
                .font(Theme.caption)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Theme.surface)
    }

    private var footer: some View {
        HStack(alignment: .top, spacing: 14) {
            Text(StyleCopy.localAdjustments)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 520, alignment: .leading)
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                ForEach(Array(StyleShortcuts.rows.enumerated()),
                        id: \.offset) { _, row in
                    HStack(spacing: 8) {
                        ForEach(row) { item in
                            HStack(spacing: 3) {
                                KeyCap(item.key)
                                Text(item.label)
                                    .font(Theme.micro)
                                    .foregroundStyle(Theme.inkMuted)
                            }
                        }
                    }
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
        .background(Theme.surface)
    }
}

/// The style sheet's keys, in one place so the footer strip and the monitor
/// can't disagree — same discipline as `Shortcuts` for the review screen.
enum StyleShortcuts {
    static let rows: [[Shortcuts.Item]] = [
        [Shortcuts.Item("1", "families"), Shortcuts.Item("2", "predict"),
         Shortcuts.Item("R", "re-predict"), Shortcuts.Item("Esc", "close")],
        [Shortcuts.Item("↑ ↓", "move"), Shortcuts.Item("J K", "move"),
         Shortcuts.Item("␣", "include / exclude"),
         Shortcuts.Item("W", "write…")],
    ]
}

// MARK: - Screen 1: look families

struct FamiliesPane: View {
    @Bindable var model: StyleModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(StyleCopy.familiesIntro)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)

                if model.loadingFamilies {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text("Clustering your edit history…")
                            .font(Theme.caption)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                } else if let fault = model.familiesFault {
                    FaultNote(fault: fault) {
                        Task { await model.loadFamilies() }
                    }
                } else if model.families.isEmpty {
                    Text("No look families.")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkMuted)
                } else {
                    ForEach(model.families) { family in
                        FamilyCard(family: family,
                                   isEffective: family.id
                                       == model.effectiveFamily) {
                            model.familyOverride = family.id
                            model.pane = .predict
                            Task { await model.predict() }
                        }
                    }
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct FamilyCard: View {
    let family: StyleFamily
    let isEffective: Bool
    let onUse: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text("Family \(family.id)")
                    .font(Theme.heading)
                    .foregroundStyle(Theme.ink)
                Text("\(family.size) edited photos")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                if isEffective {
                    HStack(spacing: 4) {
                        StateSwatch(color: Theme.pick)
                        Text("used for this shoot")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(Theme.surfaceRaised, in: Capsule())
                }
                Spacer()
                Button("Use for this shoot") { onUse() }
                    .font(Theme.caption)
            }

            // The engine's trait label, verbatim.
            Text(family.traits)
                .font(Theme.value)
                .foregroundStyle(Theme.inkSecondary)

            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("SAMPLE PHOTOS")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                    HStack(spacing: 6) {
                        ForEach(family.samplePhotoIds, id: \.self) { pid in
                            StyleThumb(photoId: pid, width: 104, height: 68)
                        }
                        if family.samplePhotoIds.isEmpty {
                            Text("none reported")
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkMuted)
                        }
                    }
                }
                VStack(alignment: .leading, spacing: 5) {
                    Text("MEDIAN EDIT")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                    if family.median.isEmpty {
                        Text("no median reported")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    } else {
                        ParamGrid(params: family.median.sorted {
                            $0.key < $1.key
                        }.map { ($0.key, $0.value) })
                    }
                }
                Spacer(minLength: 0)
            }
        }
        .padding(14)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Screen 2: prediction preview

struct PredictPane: View {
    @Bindable var model: StyleModel
    let shoot: Shoot

    var body: some View {
        VStack(spacing: 0) {
            controls
            Divider().overlay(Theme.hairline)
            if model.predicting {
                centered {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text("Asking the engine for predictions…")
                            .font(Theme.caption)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                }
            } else if let fault = model.predictFault {
                centered {
                    FaultNote(fault: fault) {
                        Task { await model.predict() }
                    }
                    .frame(maxWidth: 520)
                }
            } else if let text = model.predictErrorText {
                centered {
                    Text(text)
                        .font(Theme.caption)
                        .foregroundStyle(Theme.warning)
                }
            } else if model.predictions.isEmpty {
                centered {
                    Text("The engine returned no predictions for this shoot.")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkMuted)
                }
            } else {
                HStack(spacing: 0) {
                    predictionList
                        .frame(width: 320)
                    Divider().overlay(Theme.hairline)
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            if let p = model.current {
                                PredictionDetail(model: model, prediction: p)
                            }
                            FilterPane(model: model)
                        }
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    private func centered<C: View>(@ViewBuilder _ content: () -> C)
        -> some View {
        VStack { Spacer(); content(); Spacer() }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(20)
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Text(StyleCopy.previewBadge)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.ink)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(Theme.surfaceRaised, in: Capsule())

                Picker("Look family", selection: $model.familyOverride) {
                    Text("Auto — engine suggests").tag(Int?.none)
                    ForEach(model.families) { f in
                        Text("Family \(f.id) · \(f.size) photos")
                            .tag(Int?.some(f.id))
                    }
                }
                .frame(width: 280)
                .onChange(of: model.familyOverride) {
                    Task { await model.predict() }
                }

                if let f = model.effectiveFamily {
                    Text(model.familyOverride == nil
                         ? "using Family \(f) (auto-suggested from scene "
                           + "similarity)"
                         : "using Family \(f)")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                }
                Spacer()
                Button("Re-predict") { Task { await model.predict() } }
                    .font(Theme.caption)
                Button("Write…") { model.showWrite = true }
                    .font(Theme.caption)
                    .disabled(model.writeIds.isEmpty)
            }

            HStack(spacing: 14) {
                CountChip(color: Theme.pick,
                          text: "\(model.writeIds.count) to write")
                CountChip(color: Theme.inkMuted,
                          text: "\(model.abstainingCount) abstaining")
                if model.excludedCount > 0 {
                    CountChip(color: Theme.override_,
                              text: "\(model.excludedCount) excluded by you")
                }
                if let pv = model.prediction?.processVersion {
                    Text("process version \(pv)")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                }
                if let traits = model.effectiveFamilyInfo?.traits {
                    Text(traits)
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                        .lineLimit(1)
                }
            }

            Text(StyleCopy.previewExplainer)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Theme.surface)
    }

    private var predictionList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(Array(model.predictions.enumerated()),
                            id: \.element.photoId) { i, p in
                        PredictionRow(
                            prediction: p,
                            isCurrent: i == model.cursor,
                            isExcluded: model.excluded.contains(p.photoId),
                            onSelect: { model.cursor = i },
                            onToggle: {
                                model.cursor = i
                                model.toggleCurrentInclusion()
                            })
                            .id(p.photoId)
                    }
                }
                .padding(.vertical, 6)
            }
            .onChange(of: model.cursor) {
                if let p = model.current {
                    withAnimation(.easeOut(duration: 0.15)) {
                        proxy.scrollTo(p.photoId)
                    }
                }
            }
        }
        .background(Theme.surface)
    }
}

struct CountChip: View {
    let color: Color
    let text: String

    var body: some View {
        HStack(spacing: 5) {
            StateSwatch(color: color)
            Text(text)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
        }
    }
}

struct PredictionRow: View {
    let prediction: StylePrediction
    let isCurrent: Bool
    let isExcluded: Bool
    let onSelect: () -> Void
    let onToggle: () -> Void

    var body: some View {
        Button(action: onSelect) {
            HStack(spacing: 8) {
                StyleThumb(photoId: prediction.photoId,
                           width: 60, height: 40)
                    .opacity(prediction.abstained || isExcluded ? 0.5 : 1)
                VStack(alignment: .leading, spacing: 2) {
                    Text("photo \(prediction.photoId)")
                        .font(Theme.caption)
                        .foregroundStyle(isCurrent ? Theme.ink
                                         : Theme.inkSecondary)
                    if prediction.abstained {
                        HStack(spacing: 4) {
                            StateSwatch(color: Theme.inkMuted)
                            Text("abstained")
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkMuted)
                        }
                    } else if isExcluded {
                        HStack(spacing: 4) {
                            StateSwatch(color: Theme.override_)
                            Text("excluded — you took it out")
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkSecondary)
                        }
                    } else {
                        HStack(spacing: 4) {
                            StateSwatch(color: Theme.pick)
                            Text("confidence "
                                 + StyleCopy.confidence(
                                    prediction.confidence))
                                .font(Theme.value)
                                .foregroundStyle(Theme.inkSecondary)
                        }
                    }
                }
                Spacer()
                if !prediction.abstained {
                    Button {
                        onToggle()
                    } label: {
                        Image(systemName: isExcluded
                              ? "square" : "checkmark.square")
                            .font(.system(size: 12))
                            .foregroundStyle(isExcluded ? Theme.inkMuted
                                             : Theme.pick)
                    }
                    .buttonStyle(.plain)
                    .help(isExcluded ? "Include in the write (Space)"
                          : "Exclude from the write (Space)")
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(isCurrent ? Theme.surfaceRaised : .clear,
                        in: RoundedRectangle(cornerRadius: 5))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 6)
    }
}

struct PredictionDetail: View {
    @Bindable var model: StyleModel
    let prediction: StylePrediction

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                StyleThumb(photoId: prediction.photoId,
                           width: 200, height: 132)
                VStack(alignment: .leading, spacing: 4) {
                    Text("photo \(prediction.photoId)")
                        .font(Theme.heading)
                        .foregroundStyle(Theme.ink)
                    if prediction.abstained {
                        Text(StyleCopy.abstainHeadline)
                            .font(Theme.caption)
                            .foregroundStyle(Theme.warning)
                        Text(StyleCopy.abstainReason(prediction.reason))
                            .font(Theme.caption)
                            .foregroundStyle(Theme.inkSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                        Text("engine reason: "
                             + (prediction.reason ?? "none"))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                        if let c = prediction.confidence {
                            Text("confidence " + StyleCopy.confidence(c)
                                 + " — below the engine's gate")
                                .font(Theme.value)
                                .foregroundStyle(Theme.inkMuted)
                        }
                        Text("Nothing will be written for this photo.")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    } else {
                        HStack(spacing: 5) {
                            StateSwatch(color: Theme.pick)
                            Text("confidence "
                                 + StyleCopy.confidence(
                                    prediction.confidence))
                                .font(Theme.value)
                                .foregroundStyle(Theme.ink)
                        }
                        Text("Engine-computed from how similar the "
                             + "neighbours are and how much they agree.")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                        if let pv = model.prediction?.processVersion {
                            Text("process version \(pv) is stamped on every "
                                 + "sidecar written")
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkMuted)
                        }
                    }
                }
                Spacer(minLength: 0)
            }

            // Parameters: never an empty list standing in for "no change".
            VStack(alignment: .leading, spacing: 6) {
                Text("PREDICTED DEVELOP SETTINGS")
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                if prediction.abstained {
                    Text("None — " + StyleCopy.abstainHeadline + ".")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.warning)
                    Text("An empty parameter list here does not mean \"no "
                         + "changes needed\"; it means the engine declined "
                         + "to guess. Edit this photo yourself.")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                } else if let params = prediction.params, !params.isEmpty {
                    ParamGrid(params: model.visibleParams(params))
                    let hidden = model.hiddenCount(in: params)
                    if hidden > 0 {
                        Text("\(hidden) more predicted, hidden by your "
                             + "display filter below — still written.")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.warning)
                    }
                    Text("Names are the crs: attributes written to the "
                         + "sidecar. Values are deltas onto this photo's "
                         + "baseline, clamped by the engine to the range "
                         + "your own edits in this family cover.")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    Text("The engine reported a prediction with no "
                         + "parameters.")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.warning)
                }
            }

            NeighborStrip(prediction: prediction)
        }
    }
}

/// "Edited like these" — the reason k-NN was chosen over a trained model
/// (design 08 §4). A bare confidence number is not an explanation.
struct NeighborStrip: View {
    let prediction: StylePrediction

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            let ids = prediction.neighborPhotoIds ?? []
            Text("EDITED LIKE THESE")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
            if ids.isEmpty {
                Text("No neighbours — the engine found nothing in this "
                     + "family close enough to this photo to blend.")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(prediction.abstained
                     ? "The \(ids.count) closest edits the engine "
                       + "considered before abstaining:"
                     : "The \(ids.count) photos from your edit history the "
                       + "blend came from:")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(ids, id: \.self) { pid in
                            VStack(spacing: 3) {
                                StyleThumb(photoId: pid,
                                           width: 96, height: 64)
                                Text("photo \(pid)")
                                    .font(Theme.micro)
                                    .foregroundStyle(Theme.inkMuted)
                            }
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }
}

/// Per-parameter toggles. Labelled for what they actually are — see
/// `StyleCopy.filterCaveat`.
struct FilterPane: View {
    @Bindable var model: StyleModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider().overlay(Theme.hairline)
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.warning)
                Text("Parameter display filter — not an opt-out")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.ink)
            }
            Text(StyleCopy.filterCaveat)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(StyleCopy.filterHueNote)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)

            LazyVGrid(columns: Array(repeating: GridItem(.flexible(),
                                                        alignment: .leading),
                                     count: 3),
                      alignment: .leading, spacing: 4) {
                ForEach(model.knownParams, id: \.self) { name in
                    Toggle(isOn: Binding(
                        get: { !model.isHidden(name) },
                        set: { _ in model.toggleHidden(name) })) {
                        Text(name)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    .toggleStyle(.checkbox)
                }
            }
            Text("Shown / hidden is remembered between sessions.")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
        }
    }
}

// MARK: - Write dialog (same shape as the select export dialog, §11.7)

struct StyleWriteDialog: View {
    @Bindable var model: StyleModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Write predicted develop settings to XMP")
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)

            if let result = model.writeResult {
                resultView(result)
            } else if let error = model.writeErrorText {
                Text(error).font(Theme.caption).foregroundStyle(.red)
                HStack { Spacer(); Button("Close") { close() } }
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
                     text: "\(model.writeIds.count) photos will get crs: "
                     + "develop settings in their XMP sidecar")
            DiffLine(icon: "minus.circle",
                     text: "\(model.abstainingCount) abstaining — no "
                     + "confident prediction, so nothing is written for them")
            if model.excludedCount > 0 {
                DiffLine(icon: "hand.raised",
                         text: "\(model.excludedCount) excluded by you — "
                         + "nothing written")
            }
            if let f = model.effectiveFamily {
                DiffLine(icon: "square.stack",
                         text: "Family \(f)"
                         + (model.prediction.map {
                             " · process version \($0.processVersion) "
                             + "stamped on every write" } ?? ""))
            }
            let hiddenShown = model.hiddenParams.count
            if hiddenShown > 0 {
                DiffLine(icon: "exclamationmark.triangle",
                         text: "Every predicted parameter is written, "
                         + "including the \(hiddenShown) you have hidden in "
                         + "the preview — the engine has no per-parameter "
                         + "opt-out yet",
                         tint: Theme.warning)
            }
            DiffLine(icon: "lock",
                     text: StyleCopy.conflictsPolicy, tint: Theme.bracket)
            DiffLine(icon: "info.circle",
                     text: "Conflicts can only be detected while writing, "
                     + "so they are reported here afterwards.")
            Text(StyleCopy.localAdjustments)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 2)
        }

        HStack {
            Spacer()
            Button("Cancel") { close() }
            // Explicit, and never the default action: no Return-key path
            // into writing to the user's files.
            Button("Write \(model.writeIds.count) sidecars") {
                Task { await model.write() }
            }
            .disabled(model.writing || model.writeIds.isEmpty)
        }
        if model.writing {
            HStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text("Writing…")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
            }
        }
    }

    @ViewBuilder
    private func resultView(_ r: StyleWriteResult) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Wrote \(r.written.count) sidecars.")
                .font(Theme.body)
                .foregroundStyle(Theme.ink)
            if !r.abstained.isEmpty {
                DiffLine(icon: "minus.circle",
                         text: "\(r.abstained.count) abstained — "
                         + StyleCopy.abstainHeadline + "; nothing written")
            }
            if !r.conflicts.isEmpty {
                DiffLine(icon: "lock",
                         text: "\(r.conflicts.count) skipped — \(r.note)",
                         tint: Theme.bracket)
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(r.conflicts.prefix(5), id: \.photoId) { c in
                        Text(c.path)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    if r.conflicts.count > 5 {
                        Text("+ \(r.conflicts.count - 5) more")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }
                }
                .padding(.leading, 17)
            }
        }

        Text(StyleCopy.readMetadataCaveat)
            .font(Theme.caption)
            .foregroundStyle(Theme.inkSecondary)
            .fixedSize(horizontal: false, vertical: true)

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

/// Engine value table: parameter name in text tokens, value monospaced so
/// columns of numbers line up and can be compared down the column.
struct ParamGrid: View {
    let params: [(String, Double)]

    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(),
                                                    alignment: .leading),
                                 count: 2),
                  alignment: .leading, spacing: 3) {
            ForEach(params, id: \.0) { name, value in
                HStack(spacing: 6) {
                    Text(name)
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                        .lineLimit(1)
                    Spacer(minLength: 6)
                    Text(StyleCopy.value(value))
                        .font(Theme.value)
                        .foregroundStyle(Theme.ink)
                }
                .frame(maxWidth: 250, alignment: .leading)
            }
        }
    }
}

/// API thumbnail (design 12 §2: grid/filmstrip images come from the API,
/// shared with the web client). Neighbours and family samples belong to
/// other shoots, so the local decode path doesn't apply.
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

/// An engine refusal with an answer attached — a 409 `insufficient_history`
/// is the expected state before a catalog import, not an error to dump raw.
struct FaultNote: View {
    let fault: EngineFault
    let onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "info.circle")
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.warning)
                Text(StyleCopy.faultTitle(fault))
                    .font(Theme.heading)
                    .foregroundStyle(Theme.ink)
            }
            if let help = StyleCopy.faultHelp(fault) {
                Text(help)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            // The engine's own sentence, kept visible: it carries the
            // current counts, which is what tells the user how far off
            // they are.
            Text("Engine: \(fault.message)")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button("Try again") { onRetry() }
                    .font(Theme.caption)
            }
        }
        .padding(14)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Keyboard (design 12 §4a: same discipline as the review screen)

/// Keys for the style sheet via an NSEvent local monitor, for the same
/// reason `KeyCatcher` uses one: first responder moves the moment the user
/// clicks a toggle or a picker, and then `onKeyPress` silently stops
/// firing. Passes everything through while the write dialog is up, so the
/// confirm dialog owns the keyboard.
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
            case 49:  // space
                model.toggleCurrentInclusion()
                return true
            default:
                break
            }
            switch event.charactersIgnoringModifiers ?? "" {
            // J / K are prev / next here too — same direction as the
            // review screen's filmstrip, so the fingers don't relearn.
            case "j": model.moveCursor(-1)
            case "k": model.moveCursor(1)
            case "1": model.pane = .families
            case "2": model.pane = .predict
            case "r": Task { await model.predict() }
            case "w":
                if !model.writeIds.isEmpty { model.showWrite = true }
            default: return false
            }
            return true
        }
    }
}
