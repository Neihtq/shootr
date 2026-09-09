import AppKit
import SwiftUI

// MARK: - Deliver the selects as files (design 07 §3.2b, 12 §4a)
//
// For the workflow with no Lightroom in it at all: cull, then hand over a
// folder of keepers. The dialog wraps the engine's safety protocol, the same
// way the XMP export dialog does — plan first, every count and caveat shown,
// and no default-yes on the one action that relocates the user's files.
//
// Every number here is the engine's: the counts, the collisions, the space
// verdict, whether the mode is even possible, and whether the originals move
// (rule 6). The client picks a folder, renders the plan, and asks.
//
// The copy is deliberately the SAME STRINGS as the web client's deliver
// dialog. Doc 12 §4a: the two clients must not describe the same action in
// different words. Where a sentence reads oddly for native, the fix is to
// change it in both, not to reword one.

enum DeliverCopy {
    static let title = "Deliver selects as files"

    static let intro =
        "Puts the keepers in a folder you choose, so you can hand them over "
        + "without Lightroom. Rejected frames are never delivered, in any "
        + "mode."

    static let chooseFolder = "Choose folder…"
    static let changeFolder = "Change…"
    static let noFolderYet = "No folder chosen yet."
    static let panelMessage = "Choose the folder to deliver the keepers into"
    static let panelPrompt = "Choose"

    static let includeAltLabel = "Also deliver the runners-up (alt)"
    static let includeAltHelp =
        "Off by default: picks only. Rejects are never included either way."

    static func modeLabel(_ mode: String) -> String {
        switch mode {
        case "hardlink": return "Hardlink"
        case "copy": return "Copy"
        case "move": return "Move"
        default: return mode
        }
    }

    /// One plain line per mode, in the order that decides it: what it costs on
    /// disk, what becomes of the originals, and any restriction. All three are
    /// shown at once — the trade-off is the choice.
    static func modeExplainer(_ mode: String) -> String {
        switch mode {
        case "hardlink":
            return "Hardlink — costs no extra disk space, and your originals "
                + "stay exactly where they are. Same drive only."
        case "copy":
            return "Copy — writes every file again at full size, and your "
                + "originals stay exactly where they are."
        case "move":
            return "Move — relocates your originals into that folder. "
                + "Nothing is deleted."
        default:
            return mode
        }
    }

    static let modes = ["hardlink", "copy", "move"]

    // -- the plan ------------------------------------------------------------

    static let planning = "Checking what would happen…"
    static let dryRunBanner =
        "Nothing has been written yet — this is what would happen."
    static let chooseFolderFirst =
        "Choose a folder to see what would happen. Nothing is written until "
        + "you confirm the plan."

    static func countLine(_ n: Int, dest: String) -> String {
        StyleCopy.plural(n, "photo") + " → \(dest)"
    }

    static let nothingToDeliver =
        "Nothing to deliver — this selection has no picks in scope."

    static func companionsLine(_ n: Int) -> String {
        StyleCopy.plural(n, "sidecar or JPEG sibling",
                         "sidecars and JPEG siblings")
        + " travel with them, so ratings aren't orphaned and RAW+JPEG pairs "
        + "aren't split."
    }

    static func renamedLine(_ n: Int) -> String {
        StyleCopy.plural(n, "name collision")
        + " — those get a numbered suffix. Nothing already in that folder is "
        + "ever overwritten."
    }

    static func alreadyPresentLine(_ n: Int) -> String {
        StyleCopy.plural(n, "file")
        + " already in that folder as the same file — skipped."
    }

    static func missingSourceLine(_ n: Int) -> String {
        StyleCopy.plural(n, "source file")
        + " could not be found and will be skipped — the drive holding "
        + (n == 1 ? "it" : "them") + " may be offline."
    }

    /// Only stated for `move`: across drives the engine copies, verifies, and
    /// unlinks only then, and that is worth knowing before starting.
    static let crossVolumeMove =
        "That folder is on a different drive, so each file is copied, "
        + "verified, and only then removed from its old location."

    static func spaceLine(needed: Int64, free: Int64?) -> String {
        "Needs " + size(needed) + "; "
        + (free.map { size($0) + " free at the destination." }
           ?? "free space at the destination could not be read.")
    }

    static let notEnoughSpace =
        "Not enough free space at the destination, so this would fail partway "
        + "through. Choose another folder, or use hardlink if the folder is on "
        + "the same drive as the photos."

    // -- the move confirmation (the only destructive-feeling action) ---------

    static let moveWarningHeading = "This moves your originals"
    static let moveWarning =
        "The files leave their current folder and afterwards exist only in "
        + "the destination. Nothing is deleted: each file is either moved "
        + "intact or left exactly where it was, and Shootr updates its own "
        + "record of where every photo lives."

    static func confirmButton(_ mode: String, count: Int) -> String {
        switch mode {
        case "hardlink": return "Hardlink " + StyleCopy.plural(count, "photo")
        case "copy": return "Copy " + StyleCopy.plural(count, "photo")
        case "move":
            return "Move " + StyleCopy.plural(count, "photo")
                + " out of their folder"
        default: return "Deliver " + StyleCopy.plural(count, "photo")
        }
    }

    static let running = "Delivering…"

    // -- the result ----------------------------------------------------------

    static func deliveredLine(_ n: Int, dest: String) -> String {
        "Delivered " + StyleCopy.plural(n, "file") + " to \(dest)."
    }

    static func failedHeading(_ n: Int) -> String {
        StyleCopy.plural(n, "file") + " could not be delivered:"
    }

    // -- faults --------------------------------------------------------------

    /// The engine's own sentence wherever it has one — `delivery_impossible`
    /// already says why the mode cannot work here and what to use instead.
    static func errorCopy(_ code: String?, message: String) -> String {
        switch code {
        case "no_selection":
            return "This shoot has no cull selection yet. Run Analyze & cull "
                + "first — delivery hands over the selection's picks."
        default:
            return message
        }
    }

    static let useCopyInstead = "Use copy instead"

    /// Bytes the engine measured, in units a person reads. Display formatting
    /// only — the space verdict itself is the engine's `enough_space`.
    ///
    /// Deliberately NOT `.byteCount`: it renders 42 GB where the web client's
    /// `size()` renders 42.0 GB, and the same plan would then report two
    /// different numbers depending on which client you opened. Same arithmetic
    /// as `web/src/components/DeliverDialog.tsx`.
    static func size(_ bytes: Int64) -> String {
        let b = Double(bytes)
        return b >= 1e9
            ? String(format: "%.1f GB", b / 1e9)
            : "\(max(1, Int((b / 1e6).rounded()))) MB"
    }
}

struct DeliverSheet: View {
    let selectionId: Int
    let api = APIClient()
    @Environment(\.dismiss) private var dismiss

    /// Hardlink is the engine's default too (§3.2b) — the cheapest mode that
    /// leaves the originals alone.
    @State private var mode = "hardlink"
    @State private var includeAlt = false
    @State private var destDir: URL?
    @State private var plan: APIClient.DeliverReport?
    @State private var result: APIClient.DeliverReport?
    @State private var errorText: String?
    /// Set when the engine refused a mode and names copy as one it has —
    /// the cross-volume hardlink case, one click from being fixed.
    @State private var offerCopy = false
    @State private var busy = false
    /// Stale-response guard for overlapping dry runs.
    @State private var token = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(DeliverCopy.title)
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)

            if let result {
                resultView(result)
            } else {
                setupView
                planSection
            }
        }
        .padding(18)
        .frame(width: 520)
        .background(Theme.surface)
        .onChange(of: mode) { check() }
        .onChange(of: includeAlt) { check() }
    }

    // MARK: setup — folder, mode, scope

    @ViewBuilder
    private var setupView: some View {
        Text(DeliverCopy.intro)
            .font(Theme.caption)
            .foregroundStyle(Theme.inkSecondary)
            .fixedSize(horizontal: false, vertical: true)

        // Native's advantage over the web client, which can only offer a text
        // field: a real folder picker, so there is no path to mistype.
        HStack(spacing: 8) {
            Button(destDir == nil ? DeliverCopy.chooseFolder
                   : DeliverCopy.changeFolder) {
                pickDestination()
            }
            .font(Theme.caption)
            Text(destDir?.path ?? DeliverCopy.noFolderYet)
                .font(Theme.value)
                .foregroundStyle(destDir == nil ? Theme.inkMuted
                                 : Theme.inkSecondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }

        VStack(alignment: .leading, spacing: 5) {
            Picker("", selection: $mode) {
                ForEach(DeliverCopy.modes, id: \.self) {
                    Text(DeliverCopy.modeLabel($0))
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            // All three trade-offs on screen, the selected one lit: choosing
            // between them is the point, so they are not hidden behind it.
            ForEach(DeliverCopy.modes, id: \.self) { m in
                Text(DeliverCopy.modeExplainer(m))
                    .font(Theme.caption)
                    // Selected move reads differently from selected
                    // hardlink/copy — the same emphasis the web dialog gives
                    // it, in this theme's status token.
                    .foregroundStyle(m != mode ? Theme.inkMuted
                                     : m == "move" ? Theme.warning : Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }

        VStack(alignment: .leading, spacing: 2) {
            Toggle(isOn: $includeAlt) {
                Text(DeliverCopy.includeAltLabel)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
            }
            .toggleStyle(.checkbox)
            // Visible, not a tooltip: "rejects are never included either way"
            // is the reassurance, and a reassurance nobody hovers over isn't
            // one. The web dialog states it in the same place.
            Text(DeliverCopy.includeAltHelp)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.leading, 19)
        }
    }

    private func pickDestination() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.message = DeliverCopy.panelMessage
        panel.prompt = DeliverCopy.panelPrompt
        if panel.runModal() == .OK, let url = panel.url {
            destDir = url
            check()
        }
    }

    // MARK: the plan — always shown before anything can run

    @ViewBuilder
    private var planSection: some View {
        Divider().overlay(Theme.hairline)

        if busy {
            HStack(spacing: 6) {
                ProgressView().controlSize(.small)
                Text(plan == nil ? DeliverCopy.planning : DeliverCopy.running)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
            }
        }
        if let errorText {
            VStack(alignment: .leading, spacing: 8) {
                Text(errorText)
                    .font(Theme.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
                if offerCopy {
                    Button(DeliverCopy.useCopyInstead) { mode = "copy" }
                        .font(Theme.caption)
                }
            }
        }
        if let p = plan {
            planView(p)
            actions(p)
        } else if destDir == nil, errorText == nil {
            Text(DeliverCopy.chooseFolderFirst)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private func planView(_ p: APIClient.DeliverReport) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(DeliverCopy.dryRunBanner)
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)

            if p.count == 0 {
                DiffLine(icon: "minus.circle",
                         text: DeliverCopy.nothingToDeliver,
                         tint: Theme.warning)
            } else {
                DiffLine(icon: "arrow.right.circle",
                         text: DeliverCopy.countLine(p.count, dest: p.destDir))
            }
            if p.companions > 0 {
                DiffLine(icon: "doc.on.doc",
                         text: DeliverCopy.companionsLine(p.companions))
            }
            if !p.renamed.isEmpty {
                DiffLine(icon: "pencil.circle",
                         text: DeliverCopy.renamedLine(p.renamed.count))
                nameList(p.renamed)
            }
            if !p.alreadyPresent.isEmpty {
                DiffLine(icon: "equal.circle",
                         text: DeliverCopy.alreadyPresentLine(
                            p.alreadyPresent.count))
                nameList(p.alreadyPresent)
            }
            if !p.missingSource.isEmpty {
                DiffLine(icon: "exclamationmark.triangle",
                         text: DeliverCopy.missingSourceLine(
                            p.missingSource.count),
                         tint: Theme.warning)
                nameList(p.missingSource)
            }
            if p.mode == "copy" {
                DiffLine(icon: "internaldrive",
                         text: DeliverCopy.spaceLine(needed: p.bytesNeeded,
                                                     free: p.freeBytes),
                         tint: p.enoughSpace ? Theme.inkSecondary
                             : Theme.warning)
                if !p.enoughSpace {
                    DiffLine(icon: "exclamationmark.triangle",
                             text: DeliverCopy.notEnoughSpace,
                             tint: Theme.warning)
                }
            }
            if p.movesOriginals && p.crossVolume {
                DiffLine(icon: "info.circle",
                         text: DeliverCopy.crossVolumeMove)
            }
        }

        // The confirm step for a move says plainly what leaves the folder and
        // what is not deleted, and it does not look like the other two modes.
        if p.movesOriginals {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.warning)
                    Text(DeliverCopy.moveWarningHeading)
                        .font(Theme.caption)
                        .foregroundStyle(Theme.ink)
                }
                Text(DeliverCopy.moveWarning)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surfaceRaised,
                        in: RoundedRectangle(cornerRadius: 5))
            .overlay(RoundedRectangle(cornerRadius: 5)
                .stroke(Theme.warning.opacity(0.55), lineWidth: 1))
        }
    }

    private func nameList(_ names: [String]) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            ForEach(names.prefix(6), id: \.self) { n in
                Text(n)
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            if names.count > 6 {
                Text("+\(names.count - 6) more")
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
            }
        }
        .padding(.leading, 17)
    }

    @ViewBuilder
    private func actions(_ p: APIClient.DeliverReport) -> some View {
        HStack {
            Spacer()
            Button("Cancel") { dismiss() }
            // Never `.defaultAction`: there is no Return-key path into moving
            // or duplicating the user's photographs.
            // Confirms the plan on screen — mode and folder come from the
            // engine's own reply, not from the controls above, so what runs
            // cannot be something the user was never shown.
            Button(DeliverCopy.confirmButton(p.mode, count: p.count)) {
                run(p)
            }
                .disabled(busy || p.count == 0
                          || (p.mode == "copy" && !p.enoughSpace))
                .tint(p.movesOriginals ? Theme.warning : nil)
        }
    }

    // MARK: result

    @ViewBuilder
    private func resultView(_ r: APIClient.DeliverReport) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(DeliverCopy.deliveredLine(r.delivered ?? 0, dest: r.destDir))
                .font(Theme.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)

            if let failed = r.failed, !failed.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text(DeliverCopy.failedHeading(failed.count))
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                    ForEach(failed.prefix(6), id: \.file) { f in
                        // The engine's reason, verbatim — a failure with no
                        // stated cause is not something the user can act on.
                        Text("\(f.file) — \(f.error)")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if failed.count > 6 {
                        Text("+\(failed.count - 6) more")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.surfaceRaised,
                            in: RoundedRectangle(cornerRadius: 5))
                .overlay(RoundedRectangle(cornerRadius: 5)
                    .stroke(Theme.warning.opacity(0.55), lineWidth: 1))
            }

            if let note = r.note {
                // Relayed as the engine wrote it, not paraphrased: it is the
                // record of what became of the originals.
                Text("Engine: \(note).")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }

        HStack {
            Spacer()
            Button("Done") { dismiss() }
        }
    }

    // MARK: calls

    /// The dry run. Re-runs on every change of folder, mode or scope, so the
    /// plan on screen always belongs to the settings on screen.
    ///
    /// Flipping modes twice quickly issues overlapping requests that can land
    /// out of order, and a stale plan is worse than no plan here — it would
    /// describe one mode while the controls showed another. Only the newest
    /// request may write state (same discipline as `ReviewModel.refreshPhoto`).
    private func check() {
        guard let dest = destDir else { return }
        token += 1
        let mine = token
        plan = nil
        result = nil
        errorText = nil
        offerCopy = false
        busy = true
        Task {
            do {
                let r = try await api.deliver(
                    selectionId: selectionId, destDir: dest.path, mode: mode,
                    includeAlt: includeAlt, confirm: false)
                guard mine == token else { return }
                plan = r
            } catch {
                guard mine == token else { return }
                fail(error)
            }
            if mine == token { busy = false }
        }
    }

    private func run(_ p: APIClient.DeliverReport) {
        token += 1
        let mine = token
        errorText = nil
        offerCopy = false
        busy = true
        Task {
            do {
                let r = try await api.deliver(
                    selectionId: selectionId, destDir: p.destDir, mode: p.mode,
                    includeAlt: includeAlt, confirm: true)
                guard mine == token else { return }
                result = r
            } catch {
                guard mine == token else { return }
                fail(error)
            }
            if mine == token { busy = false }
        }
    }

    private func fail(_ error: Error) {
        guard let apiError = error as? APIError else {
            errorText = String(describing: error)
            return
        }
        errorText = DeliverCopy.errorCopy(apiError.code,
                                          message: apiError.description)
        // Cross-volume hardlink: the engine says use copy, so offer the click
        // rather than making the user find the picker again.
        offerCopy = apiError.code == "delivery_impossible" && mode != "copy"
            && (apiError.detail?.modes?.contains("copy") ?? true)
    }
}
