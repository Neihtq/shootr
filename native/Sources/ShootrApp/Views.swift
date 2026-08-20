import ShootrKit
import SwiftUI

// MARK: - App shell

struct RootView: View {
    @State private var model = ReviewModel()

    var body: some View {
        Group {
            if model.shoot == nil {
                ShootListView(model: model)
            } else {
                GroupReviewView(model: model)
            }
        }
        .background(Theme.bg)
        .preferredColorScheme(.dark)  // neutral chrome; color judgement (§11.8)
        .task { await model.loadHome() }
    }
}

// MARK: - Shoot list (subset scope: pick a shoot, nothing else — §12.3)

struct ShootListView: View {
    @Bindable var model: ReviewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text("Shootr")
                    .font(Theme.heading)
                    .foregroundStyle(Theme.ink)
                Text("web UI: http://127.0.0.1:8721/ui")
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                    .textSelection(.enabled)
                Spacer()
                if let status = model.analyzeStatus {
                    HStack(spacing: 5) {
                        ProgressView().controlSize(.mini)
                        Text(status)
                            .font(Theme.caption)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                }
                Button {
                    pickFolder()
                } label: {
                    Label("Add library…", systemImage: "folder.badge.plus")
                        .font(Theme.caption)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)

            if let err = model.errorMessage {
                Label(err, systemImage: "bolt.horizontal.circle")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 10)
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    if !model.libraries.isEmpty {
                        SectionHeader("Libraries")
                        ForEach(model.libraries, id: \.id) { lib in
                            LibraryRow(library: lib) {
                                Task { await model.removeLibrary(lib.id) }
                            }
                        }
                    }
                    if !model.proposals.isEmpty {
                        SectionHeader("Proposed shoots — pick a genre")
                        ForEach(Array(model.proposals.enumerated()),
                                id: \.offset) { _, p in
                            ProposalCard(proposal: p) { name, profile in
                                Task {
                                    await model.confirmProposal(
                                        p, name: name, profile: profile)
                                }
                            }
                        }
                    }
                    if !model.shoots.isEmpty {
                        SectionHeader("Shoots")
                        ForEach(model.shoots) { shoot in
                            ShootCard(
                                shoot: shoot,
                                progress: model.analyzingShootId == shoot.id
                                    ? model.analyzeProgress : nil,
                                onAnalyze: {
                                    Task { await model.analyzeShoot(shoot) }
                                },
                                action: {
                                    Task { await model.open(shoot: shoot) }
                                })
                        }
                    }
                }
                .padding(.horizontal, 20)
            }
        }
        .frame(minWidth: 560, minHeight: 480)
        .background(Theme.bg)
    }

    /// Native folder picker — no path pasting (the web client can't have
    /// this; it's one of the reasons a native client exists).
    private func pickFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Choose a photo folder to add as a library"
        panel.prompt = "Add & scan"
        if panel.runModal() == .OK, let url = panel.url {
            Task { await model.addLibrary(path: url.path) }
        }
    }
}

struct SectionHeader: View {
    let title: String
    init(_ title: String) { self.title = title }
    var body: some View {
        Text(title)
            .font(Theme.micro)
            .textCase(.uppercase)
            .foregroundStyle(Theme.inkMuted)
            .padding(.top, 10)
    }
}

struct LibraryRow: View {
    let library: Library
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(library.online ? Theme.pick : Theme.bracket)
                .frame(width: 6, height: 6)
            Text(library.rootPath)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
                .lineLimit(1)
                .truncationMode(.middle)
            if !library.online {
                Text("offline")
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
            }
            Spacer()
            Button("Remove") {
                let alert = NSAlert()
                alert.messageText = "Remove this library from Shootr?"
                alert.informativeText =
                    "\(library.rootPath)\n\nScan data, analysis, and " +
                    "selections are removed from the app. Your photo " +
                    "files are NOT touched."
                alert.addButton(withTitle: "Remove")
                alert.addButton(withTitle: "Cancel")
                if alert.runModal() == .alertFirstButtonReturn {
                    onRemove()
                }
            }
            .font(Theme.micro)
            .buttonStyle(.plain)
            .foregroundStyle(Theme.inkMuted)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 6))
    }
}

struct ProposalCard: View {
    let proposal: APIClient.Proposal
    let onConfirm: (String, String) -> Void

    @State private var name: String = ""
    @State private var profile = "event"

    private var defaultName: String {
        let dir = proposal.directories.last ?? ""
        let day = proposal.start?.prefix(10) ?? "undated"
        return dir != "." && !dir.isEmpty ? dir : String(day)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text("\(proposal.photoIds.count) photos")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.ink)
                if let start = proposal.start {
                    Text("\(start.prefix(10)) → \(proposal.end?.prefix(10) ?? "")")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                }
                Spacer()
            }
            HStack(spacing: 8) {
                TextField("Name", text: $name, prompt: Text(defaultName))
                    .textFieldStyle(.roundedBorder)
                    .font(Theme.body)
                Picker("", selection: $profile) {
                    ForEach(["portrait", "event", "landscape", "street"],
                            id: \.self) { Text($0) }
                }
                .frame(width: 110)
                Button("Create & analyze") {
                    onConfirm(name.isEmpty ? defaultName : name, profile)
                }
            }
        }
        .padding(12)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
    }
}

struct ShootCard: View {
    let shoot: Shoot
    var progress: (completed: Int, total: Int)?
    var onAnalyze: (() -> Void)?
    let action: () -> Void
    @State private var hovering = false

    /// Busy = work in flight, per the engine. Local `progress` is the
    /// live-polled view of the same thing; either one means "not yet".
    private var busy: Bool { shoot.isBusy || progress != nil }
    /// Nothing culled yet and nothing running: the only useful action is
    /// "Analyze & cull", so opening it would show an empty review.
    private var openable: Bool { !busy && shoot.latestSelectionId != nil }

    var body: some View {
        Button(action: action) {
            VStack(spacing: 10) {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(shoot.name)
                            .font(Theme.heading)
                            .foregroundStyle(openable ? Theme.ink
                                             : Theme.inkSecondary)
                        HStack(spacing: 6) {
                            Text(shoot.profile)
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkSecondary)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Theme.surfaceRaised, in: Capsule())
                            Text("\(shoot.photoCount) photos")
                                .font(Theme.caption)
                                .foregroundStyle(Theme.inkSecondary)
                            if busy {
                                HStack(spacing: 4) {
                                    ProgressView().controlSize(.mini)
                                    Text("culling — opens when done")
                                        .font(Theme.caption)
                                        .foregroundStyle(Theme.inkSecondary)
                                }
                            } else if let stopped = shoot.stoppedLabel {
                                // Analysis stopped partway. The work is
                                // checkpointed, so report it plainly instead
                                // of showing hours of analysis as nothing.
                                Text("\(stopped) "
                                     + "(\(shoot.analyzedCount)/"
                                     + "\(shoot.photoCount) analyzed)")
                                    .font(Theme.caption)
                                    .foregroundStyle(Theme.warning)
                            } else if shoot.latestSelectionId != nil {
                                HStack(spacing: 4) {
                                    StateSwatch(color: Theme.pick)
                                    Text("culled")
                                        .font(Theme.caption)
                                        .foregroundStyle(Theme.inkSecondary)
                                }
                            } else {
                                Text("not culled yet")
                                    .font(Theme.caption)
                                    .foregroundStyle(Theme.inkMuted)
                            }
                        }
                    }
                    Spacer()
                    if !busy, let onAnalyze {
                        Button(shoot.isStopped ? "Resume"
                               : shoot.latestSelectionId == nil
                               ? "Analyze & cull" : "Re-cull") {
                            onAnalyze()
                        }
                        .font(Theme.caption)
                        .buttonStyle(.bordered)
                    }
                    // No affordance when there is nowhere to go.
                    if openable {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(Theme.inkMuted)
                    }
                }
                if let p = progress {
                    AnalyzeProgressBar(completed: p.completed, total: p.total)
                } else if busy {
                    // Busy per the engine but this client isn't the one
                    // polling (relaunched, or the web UI started it) —
                    // show indeterminate rather than a stale bar.
                    AnalyzeProgressBar(
                        completed: shoot.analyzedCount, total: shoot.photoCount)
                }
            }
            .padding(14)
            .background(
                hovering && openable ? Theme.surfaceRaised : Theme.surface,
                in: RoundedRectangle(cornerRadius: 8))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!openable)
        .onHover { hovering = $0 }
        .help(busy ? "Culling in progress — the shoot opens when it finishes"
              : openable ? "Open for review"
              : shoot.isStopped
                ? "Analysis stopped partway — Resume continues where it "
                  + "left off"
              : "Run Analyze & cull first")
    }
}

/// Determinate analyze progress: thin capsule (meter spec — fill + lighter
/// track), count + percent in text tokens beside it.
struct AnalyzeProgressBar: View {
    let completed: Int
    let total: Int

    private var fraction: Double {
        total > 0 ? Double(completed) / Double(total) : 0
    }

    var body: some View {
        HStack(spacing: 10) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.meterTrack)
                    Capsule()
                        .fill(Theme.pick)
                        .frame(width: max(4, geo.size.width * fraction))
                        .animation(.easeOut(duration: 0.6), value: fraction)
                }
            }
            .frame(height: 5)
            Text("\(completed)/\(total) · \(Int(fraction * 100))%")
                .font(Theme.value)
                .foregroundStyle(Theme.inkSecondary)
                .frame(width: 110, alignment: .trailing)
        }
    }
}

// MARK: - Group review (the culling instrument — §12.3)

struct GroupReviewView: View {
    @Bindable var model: ReviewModel

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Theme.hairline)
            HStack(spacing: 0) {
                groupSidebar
                    .frame(width: 168)
                Divider().overlay(Theme.hairline)
                VStack(spacing: 0) {
                    filmstrip
                    Divider().overlay(Theme.hairline)
                    LoupeView(model: model)
                    Divider().overlay(Theme.hairline)
                    actionBar
                }
                if model.showEvidence, let photo = model.photo {
                    Divider().overlay(Theme.hairline)
                    EvidenceView(photo: photo)
                        .frame(width: 248)
                }
            }
        }
        .background(KeyCatcher(model: model))
        .background(Theme.bg)
        .frame(minWidth: 1040, minHeight: 660)
        .sheet(isPresented: $model.showExport) {
            if let selId = model.shoot?.latestSelectionId {
                ExportSheet(selectionId: selId)
            }
        }
        .sheet(isPresented: $model.showSettings) {
            ShootSettingsSheet(model: model)
        }
        .sheet(isPresented: $model.comparing) {
            CompareSheet(photoIds: model.compareIds, model: model)
        }
        .sheet(isPresented: $model.showShortcuts) {
            ShortcutsSheet(profile: model.shoot?.profile ?? "event")
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Button {
                model.shoot = nil
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 10, weight: .semibold))
                    Text(model.shoot?.name ?? "")
                        .font(Theme.body)
                }
                .foregroundStyle(Theme.inkSecondary)
            }
            .buttonStyle(.plain)

            if let g = model.currentGroup {
                Text("Group \(model.groupIndex + 1) of \(model.groups.count)")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkMuted)
                if g.isBracket {
                    HStack(spacing: 4) {
                        StateSwatch(color: Theme.bracket)
                        Text("exposure bracket — all frames kept")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    .padding(.horizontal, 7)
                    .padding(.vertical, 3)
                    .background(Theme.surfaceRaised, in: Capsule())
                }
            }
            Spacer()
            Toggle(isOn: $model.showEvidence) {
                Text("Evidence")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
            }
            .toggleStyle(.checkbox)
            Button {
                model.showSettings = true
            } label: {
                Image(systemName: "slider.horizontal.3")
                    .font(.system(size: 11))
            }
            .help("Shoot settings — rename, change genre (instant rescore)")
            Button("Export…") {
                model.showExport = true
            }
            .font(Theme.caption)
            .disabled(model.shoot?.latestSelectionId == nil)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
        .background(Theme.surface)
    }

    private var groupSidebar: some View {
        ScrollView {
            LazyVStack(spacing: 1) {
                ForEach(Array(model.groups.enumerated()), id: \.element.id) { i, group in
                    GroupRow(
                        group: group,
                        ordinal: i + 1,
                        pickCount: group.photoIds.filter {
                            model.entryByPhoto[$0]?.state == "pick"
                        }.count,
                        isCurrent: i == model.groupIndex
                    ) {
                        model.groupIndex = i
                        model.frameIndex = 0
                        Task { await model.refreshPhoto() }
                    }
                }
            }
            .padding(.vertical, 4)
        }
        .background(Theme.surface)
    }

    private var filmstrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                if let g = model.currentGroup {
                    ForEach(Array(g.photoIds.enumerated()), id: \.element) { i, pid in
                        FilmstripThumb(
                            photoId: pid,
                            state: g.isBracket ? nil
                                : model.entryByPhoto[pid]?.state,
                            isOverride:
                                model.entryByPhoto[pid]?.userOverride == 1,
                            isBracket: g.isBracket,
                            isCurrent: i == model.frameIndex
                        ) {
                            model.frameIndex = i
                            Task { await model.refreshPhoto() }
                        }
                    }
                }
            }
            .padding(10)
        }
        .frame(height: 104)
        .background(Theme.surface)
    }

    private var actionBar: some View {
        HStack(spacing: 10) {
            if let sel = model.photo?.selection {
                StateSwatch(color: sel.userOverride
                    ? Theme.override_ : Theme.stateColor(sel.state))
                Text(sel.reason)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                    .lineLimit(1)
            }
            Spacer()
            if let photo = model.photo, !photo.exifLine.isEmpty {
                Text(photo.exifLine)
                    .font(Theme.value)
                    .foregroundStyle(Theme.inkSecondary)
            }
            KeyHints { model.showShortcuts = true }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Theme.surface)
    }
}

struct GroupRow: View {
    let group: PhotoGroup
    let ordinal: Int
    let pickCount: Int
    let isCurrent: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 7) {
                if group.isBracket {
                    StateSwatch(color: Theme.bracket)
                } else if pickCount > 0 {
                    StateSwatch(color: Theme.pick)
                } else {
                    StateSwatch(color: Theme.hairline)
                }
                Text("Group \(ordinal)")
                    .font(Theme.body)
                    .foregroundStyle(isCurrent ? Theme.ink : Theme.inkSecondary)
                Spacer()
                Text(group.isBracket ? "HDR" : "\(group.photoIds.count)")
                    .font(Theme.value)
                    .foregroundStyle(Theme.inkMuted)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(isCurrent ? Theme.surfaceRaised : .clear,
                        in: RoundedRectangle(cornerRadius: 5))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 6)
    }
}

struct FilmstripThumb: View {
    let photoId: Int
    let state: String?
    let isOverride: Bool
    let isBracket: Bool
    let isCurrent: Bool
    let action: () -> Void

    private var stateColor: Color {
        if isBracket { return Theme.bracket }
        if isOverride { return Theme.override_ }
        return Theme.stateColor(state)
    }

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                AsyncImage(url: APIClient().thumbURL(photoId: photoId,
                                                     size: 256)) {
                    $0.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Rectangle().fill(Theme.surfaceRaised)
                }
                .frame(width: 104, height: 68)
                .clipShape(RoundedRectangle(cornerRadius: 4))
                .opacity(state == "reject" ? 0.45 : 1)
                .overlay(
                    RoundedRectangle(cornerRadius: 4)
                        .stroke(isCurrent ? Theme.ink : .clear, lineWidth: 2))

                // State strip under the frame: color + label, never
                // color alone.
                HStack(spacing: 3) {
                    RoundedRectangle(cornerRadius: 1)
                        .fill(stateColor)
                        .frame(width: 14, height: 3)
                    if let state, !isBracket {
                        Text(state.uppercased() + (isOverride ? "*" : ""))
                            .font(Theme.micro)
                            .foregroundStyle(
                                state == "reject" ? Theme.inkMuted
                                    : Theme.inkSecondary)
                    }
                }
                .frame(height: 10)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// The one canonical shortcut list, shared by the action-bar strip and the
/// `?` sheet so they can never disagree. Grouped the way the work is done:
/// move, judge, inspect.
enum Shortcuts {
    struct Item: Identifiable {
        let key: String
        let label: String
        /// Longer gloss for the sheet — the action-bar strip shows `label`
        /// only. Overlays get one because a red grid with no name is not
        /// evidence the user can act on.
        let detail: String?
        var id: String { key }

        init(_ key: String, _ label: String, _ detail: String? = nil) {
            self.key = key
            self.label = label
            self.detail = detail
        }
    }

    static let navigate: [Item] = [
        Item("← →", "prev / next frame", "also J / K"),
        Item("↑ ↓", "prev / next group", "also G / ⇧G"),
        Item("Home / End", "first / last frame in group"),
        Item("Esc", "back to shoots"),
    ]

    static let judge: [Item] = [
        Item("P", "pick", "recommended keeper — 3★ on export"),
        Item("A", "alt", "credible runner-up — 2★ on export"),
        Item("X", "reject", "not chosen; nothing is ever deleted"),
        Item("␣", "toggle pick ↔ reject"),
    ]

    static let inspect: [Item] = [
        Item("Z", "100% zoom", "snaps to the primary face; drag to pan"),
        Item("C", "compare", "current frame vs the group's runner-ups"),
        Item("S", "sharpness heatmap",
             "red = sharpest tiles in THIS frame — shows where focus landed"),
        Item("O", "composition overlay", "thirds grid + face boxes"),
        Item("B", "eye crops", "full-res eyes of the primary face — blink check"),
        Item("E", "evidence panel", "per-metric scores behind the verdict"),
        Item("?", "this list"),
    ]

    /// The compact subset for the always-visible strip.
    static let strip: [Item] = [
        Item("P", "pick"), Item("A", "alt"), Item("X", "reject"),
        Item("S", "sharpness"), Item("O", "faces"), Item("?", "keys"),
    ]
}

struct KeyHints: View {
    /// Tapping the strip opens the full sheet — the shortcuts have to be
    /// reachable by mouse too, or they're only discoverable by already
    /// knowing them.
    var onShowAll: (() -> Void)?

    var body: some View {
        HStack(spacing: 10) {
            ForEach(Shortcuts.strip) { item in
                HStack(spacing: 3) {
                    KeyCap(item.key)
                    Text(item.label)
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { onShowAll?() }
        .help("Show all keyboard shortcuts (?)")
    }
}

struct KeyCap: View {
    let key: String
    init(_ key: String) { self.key = key }

    var body: some View {
        Text(key)
            .font(Theme.micro)
            .foregroundStyle(Theme.inkSecondary)
            .padding(.horizontal, 4)
            .padding(.vertical, 1.5)
            .background(Theme.surfaceRaised,
                        in: RoundedRectangle(cornerRadius: 3))
    }
}

/// `?` — the full shortcut reference, plus how the engine reached its
/// verdicts. Both were README-only before, which is the wrong place for
/// something you need while looking at a photo.
struct ShortcutsSheet: View {
    let profile: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Keyboard")
                    .font(Theme.heading)
                    .foregroundStyle(Theme.ink)
                Spacer()
                Button("Close") { dismiss() }
                    .font(Theme.caption)
            }
            .padding(.bottom, 14)

            HStack(alignment: .top, spacing: 26) {
                section("Move", Shortcuts.navigate)
                section("Judge", Shortcuts.judge)
                section("Inspect", Shortcuts.inspect)
            }

            Divider().overlay(Theme.hairline).padding(.vertical, 14)

            HowVerdictsWork(profile: profile)
        }
        .padding(20)
        .frame(width: 720)
        .background(Theme.surface)
        .onKeyPress(.escape) { dismiss(); return .handled }
    }

    private func section(_ title: String,
                         _ items: [Shortcuts.Item]) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title.uppercased())
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .padding(.bottom, 1)
            ForEach(items) { item in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    KeyCap(item.key)
                        .frame(width: 54, alignment: .leading)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.label)
                            .font(Theme.caption)
                            .foregroundStyle(Theme.inkSecondary)
                        if let detail = item.detail {
                            Text(detail)
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkMuted)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The engine proposes every pick/alt/reject; a user who doesn't know that,
/// or on what basis, can't sensibly disagree with it (design 06 §1).
struct HowVerdictsWork: View {
    let profile: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("HOW THE VERDICTS ARE CHOSEN")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)

            Text("Every pick / alt / reject is proposed automatically, per "
                 + "group, from each frame's quality score under this "
                 + "shoot's genre (\(profile)). Your changes always win and "
                 + "survive re-culling.")
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: 4) {
                rule(Theme.bracket, "Exposure bracket",
                     "every frame kept — brackets are never culled.")
                rule(Theme.pick, "Best few in the group",
                     "ranked by score, with a penalty for looking too much "
                     + "like a frame already picked, then a preference for "
                     + "fewest blinking subjects.")
                rule(Theme.alt, "Next one down",
                     "the runner-up, kept for comparison. Also where a whole "
                     + "group lands when no frame clears the quality floor — "
                     + "the engine declines to recommend rather than guess.")
                rule(Theme.reject, "Everything else",
                     "not chosen. Nothing is deleted or moved, and rejects "
                     + "write nothing on export.")
            }

            Text("The reason for the current frame is always in the bar "
                 + "below the photo; press E for the per-metric scores "
                 + "behind it.")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func rule(_ color: Color, _ title: String,
                      _ text: String) -> some View {
        // Swatch beside the words, never color-carrying-meaning alone.
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            StateSwatch(color: color)
            Group {
                Text(title + " — ").foregroundStyle(Theme.inkSecondary)
                    + Text(text).foregroundStyle(Theme.inkMuted)
            }
            .font(Theme.caption)
            .fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - Loupe: local full-res decode where native wins (§12.4)

struct LoupeView: View {
    @Bindable var model: ReviewModel
    @State private var image: NSImage?
    @State private var loadedFor: Int?
    @State private var dragOffset: CGSize = .zero
    @State private var panBase: CGSize = .zero

    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color.black
                if let image {
                    if model.zoomed {
                        zoomedImage(image, in: geo.size)
                    } else {
                        Image(nsImage: image)
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .overlay {
                                if model.showSharpness,
                                   let pid = model.currentPhotoId {
                                    // Heatmap over the fitted image area.
                                    FittedOverlay(imageSize: image.size) {
                                        SharpnessOverlay(photoId: pid)
                                    }
                                }
                                // Only draw face boxes when the detail on
                                // hand belongs to the frame on screen —
                                // otherwise the previous photo's boxes land
                                // on this one during the fetch.
                                if model.showComposition,
                                   let photo = model.photo,
                                   photo.id == loadedFor {
                                    FittedOverlay(imageSize: image.size) {
                                        CompositionOverlay(photo: photo)
                                    }
                                }
                                // Same stale-guard as composition: only the
                                // on-screen frame's eyes.
                                if model.showEyes,
                                   let photo = model.photo,
                                   photo.id == loadedFor {
                                    EyeOverlay(photo: photo)
                                }
                            }
                    }
                } else {
                    ProgressView()
                        .controlSize(.small)
                }
                if model.zoomed {
                    Text("100%")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkSecondary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(.black.opacity(0.6), in: Capsule())
                        .frame(maxWidth: .infinity, maxHeight: .infinity,
                               alignment: .topTrailing)
                        .padding(8)
                }
            }
        }
        .clipped()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        // Trackpad pinch: in = 100% (face-snapped), out = fit (§12.4).
        .gesture(
            MagnifyGesture()
                .onEnded { value in
                    model.zoomed = value.magnification > 1
                }
        )
        // Keyed on the id the view is asked to show, and it loads from THAT
        // id — not from `model.photo`. Reading model.photo here raced: the
        // task fires as soon as currentPhotoId changes (synchronous), while
        // model.photo still holds the previous group's detail. The guard
        // then saw loadedFor == photo.id, returned early, and nothing
        // re-fired — leaving the previous group's image under a filmstrip
        // that had already moved on.
        .task(id: model.currentPhotoId) {
            guard let pid = model.currentPhotoId else {
                image = nil
                loadedFor = nil
                return
            }
            if loadedFor == pid, image != nil { return }
            // Clear first: showing the old frame while the new one decodes
            // is how a wrong-photo read happens in the first place.
            image = nil
            loadedFor = nil
            dragOffset = .zero
            panBase = .zero
            // Two-stage load: the 2048 thumbnail (server-cached, fast) goes
            // up immediately so skimming groups never stares at a spinner;
            // the local full-res decode replaces it when ready. Both stages
            // re-check the current id — same stale-read discipline as the
            // single-stage version.
            if let quick = await ImagePipeline.shared.quickImage(photoId: pid) {
                guard !Task.isCancelled, model.currentPhotoId == pid
                else { return }
                image = quick
                loadedFor = pid
            }
            let detail = model.photo?.id == pid
                ? model.photo
                : try? await model.api.photo(pid)
            guard let detail, !Task.isCancelled else { return }
            let loaded = await ImagePipeline.shared.loupeImage(
                photo: detail, libraryRoot: model.libraryRoot)
            // A newer frame may have been selected while this decoded.
            guard !Task.isCancelled, model.currentPhotoId == pid else { return }
            if let loaded { image = loaded }
            loadedFor = pid
        }
        .onChange(of: model.zoomed) {
            dragOffset = .zero
            panBase = .zero
        }
    }

    /// 100% pixels, initially centered on the primary face (design 11 §4),
    /// draggable to pan. This is where the local full-res decode pays off.
    private func zoomedImage(_ img: NSImage, in container: CGSize) -> some View {
        let px = img.representations.first.map {
            CGSize(width: $0.pixelsWide, height: $0.pixelsHigh)
        } ?? img.size

        // Center of interest: primary face bbox center (Vision origin is
        // bottom-left → flip y), else image center.
        var cx = 0.5, cy = 0.5
        if let f = model.photo?.faces.first, f.bbox.count == 4 {
            cx = f.bbox[0] + f.bbox[2] / 2
            cy = 1 - (f.bbox[1] + f.bbox[3] / 2)
        }
        let offset = CGSize(
            width: (0.5 - cx) * px.width + dragOffset.width,
            height: (0.5 - cy) * px.height + dragOffset.height)

        return Image(nsImage: img)
            .resizable()
            .frame(width: px.width, height: px.height)
            .offset(offset)
            .gesture(
                DragGesture()
                    .onChanged { v in
                        dragOffset = CGSize(
                            width: panBase.width + v.translation.width,
                            height: panBase.height + v.translation.height)
                    }
                    .onEnded { _ in panBase = dragOffset }
            )
    }
}

// MARK: - Evidence panel: renders engine records verbatim (§10.3)

struct EvidenceView: View {
    let photo: PhotoDetail

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let score = photo.score {
                    // Hero number: the total, with profile as context.
                    VStack(alignment: .leading, spacing: 2) {
                        Text(String(format: "%.2f", score.total))
                            .font(.system(size: 26, weight: .semibold))
                            .foregroundStyle(Theme.ink)
                        Text("\(score.profile) profile")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }

                    VStack(alignment: .leading, spacing: 9) {
                        ForEach(score.components.keys.sorted(),
                                id: \.self) { name in
                            if let comp = score.components[name] {
                                ComponentBar(name: name, comp: comp)
                            }
                        }
                    }

                    if !score.flags.isEmpty {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("Flags")
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkMuted)
                                .textCase(.uppercase)
                            FlowFlags(flags: score.flags)
                        }
                    }
                } else {
                    Text("Not scored yet")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkMuted)
                }

                // Capture info — from EXIF, probed at ingest.
                VStack(alignment: .leading, spacing: 3) {
                    Text("Capture")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                        .textCase(.uppercase)
                    if !photo.exifLine.isEmpty {
                        Text(photo.exifLine)
                            .font(Theme.value)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    if let cam = photo.cameraModel {
                        Text(cam)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }
                    if let lens = photo.lensModel {
                        Text(lens)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                            .lineLimit(1)
                    }
                    if let t = photo.capturedAt {
                        Text(t.replacingOccurrences(of: "T", with: "  "))
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkMuted)
                    }
                }
                .padding(.top, 4)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Theme.surface)
    }
}

struct ComponentBar: View {
    let name: String
    let comp: ScoreComponent

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(name.replacingOccurrences(of: "_", with: " "))
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                Spacer()
                // nil = not applicable / abstained: dash, NEVER a zero bar.
                Text(comp.value.map { String(format: "%.2f", $0) } ?? "—")
                    .font(Theme.value)
                    .foregroundStyle(comp.value == nil
                        ? Theme.inkMuted : Theme.ink)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    // Meter spec: 5px, rounded, fill + lighter track of the
                    // same neutral ramp; the track goes transparent for
                    // null so "not measured" never reads as "empty".
                    Capsule()
                        .fill(comp.value == nil ? .clear : Theme.meterTrack)
                    if let v = comp.value {
                        Capsule()
                            .fill(Theme.meterFill)
                            .frame(width: max(3, geo.size.width * v))
                    }
                }
            }
            .frame(height: 5)
        }
    }
}

/// Flags as quiet tags; amber swatch carries "attention", text stays in
/// text tokens.
struct FlowFlags: View {
    let flags: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(flags, id: \.self) { flag in
                HStack(spacing: 5) {
                    StateSwatch(color: Theme.bracket)
                    Text(flag)
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkSecondary)
                        .lineLimit(1)
                }
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                .background(Theme.surfaceRaised,
                            in: RoundedRectangle(cornerRadius: 4))
            }
        }
    }
}

// MARK: - Keyboard (identical bindings to web — §12.4)

/// Keyboard via an NSEvent LOCAL MONITOR, not first responder.
///
/// The first-responder approach breaks silently: `makeFirstResponder` at
/// view-creation runs before the view is in a window (window == nil, no-op),
/// and every click on a button/toggle moves first responder away with
/// nothing to restore it. A local monitor sees keyDown regardless of focus.
/// Keys are passed through (returned) while a text field is editing so
/// typing a shoot name doesn't trigger culling actions.
struct KeyCatcher: NSViewRepresentable {
    let model: ReviewModel

    func makeNSView(context: Context) -> NSView {
        context.coordinator.install(model: model)
        return NSView()
    }

    func updateNSView(_ view: NSView, context: Context) {
        context.coordinator.model = model
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    static func dismantleNSView(_ view: NSView, coordinator: Coordinator) {
        coordinator.remove()
    }

    @MainActor
    final class Coordinator {
        var model: ReviewModel?
        private var monitor: Any?

        func install(model: ReviewModel) {
            self.model = model
            guard monitor == nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) {
                [weak self] event in
                guard let self, let model = self.model else { return event }
                // Sheets own the keyboard while open (compare handles its
                // own Z; export/settings are form UIs).
                if model.comparing || model.showExport || model.showSettings
                    || model.showShortcuts {
                    return event
                }
                // Don't steal keys from an active text field (the field
                // editor is an NSTextView).
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

        private func handle(_ event: NSEvent, model: ReviewModel) -> Bool {
            switch event.keyCode {
            case 123:  // ←
                Task { await model.prevFrame() }
                return true
            case 124:  // →
                Task { await model.nextFrame() }
                return true
            case 125:  // ↓
                Task { await model.nextGroup() }
                return true
            case 126:  // ↑
                Task { await model.prevGroup() }
                return true
            case 49:  // space — toggle pick ↔ reject
                Task { await model.togglePick() }
                return true
            case 53:  // escape — back to shoot list
                model.shoot = nil
                return true
            case 115:  // home
                Task { await model.firstFrame() }
                return true
            case 119:  // end
                Task { await model.lastFrame() }
                return true
            default:
                break
            }
            switch event.charactersIgnoringModifiers ?? "" {
            case "j": Task { await model.prevFrame() }
            case "k": Task { await model.nextFrame() }
            case "g": Task { await model.nextGroup() }
            case "G": Task { await model.prevGroup() }
            case "p": Task { await model.setState("pick") }
            case "a": Task { await model.setState("alt") }
            case "x": Task { await model.setState("reject") }
            case "e": model.showEvidence.toggle()
            case "z": model.zoomed.toggle()
            case "s": model.showSharpness.toggle()
            case "o": model.showComposition.toggle()
            case "b": model.showEyes.toggle()
            // "/" too: ? is shift-/ on US layouts but not on every layout,
            // and the unshifted key is what people actually press.
            case "?", "/": model.showShortcuts = true
            case "c":
                if model.compareIds.count >= 2 { model.comparing.toggle() }
            default: return false
            }
            return true
        }
    }
}
