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

    var body: some View {
        Button(action: action) {
            VStack(spacing: 10) {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(shoot.name)
                            .font(Theme.heading)
                            .foregroundStyle(Theme.ink)
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
                            if shoot.latestSelectionId != nil,
                               progress == nil {
                                HStack(spacing: 4) {
                                    StateSwatch(color: Theme.pick)
                                    Text("culled")
                                        .font(Theme.caption)
                                        .foregroundStyle(Theme.inkSecondary)
                                }
                            }
                        }
                    }
                    Spacer()
                    if progress == nil, let onAnalyze {
                        Button(shoot.latestSelectionId == nil
                               ? "Analyze & cull" : "Re-cull") {
                            onAnalyze()
                        }
                        .font(Theme.caption)
                        .buttonStyle(.bordered)
                    }
                    Image(systemName: "chevron.right")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Theme.inkMuted)
                }
                if let p = progress {
                    AnalyzeProgressBar(completed: p.completed, total: p.total)
                }
            }
            .padding(14)
            .background(
                hovering ? Theme.surfaceRaised : Theme.surface,
                in: RoundedRectangle(cornerRadius: 8))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
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
            KeyHints()
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

struct KeyHints: View {
    private let hints: [(String, String)] = [
        ("P", "pick"), ("A", "alt"), ("X", "reject"), ("␣", "toggle"),
        ("← →", "frames"), ("↑ ↓", "groups"), ("Z", "100%"),
    ]

    var body: some View {
        HStack(spacing: 10) {
            ForEach(hints, id: \.0) { key, label in
                HStack(spacing: 3) {
                    Text(key)
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkSecondary)
                        .padding(.horizontal, 4)
                        .padding(.vertical, 1.5)
                        .background(Theme.surfaceRaised,
                                    in: RoundedRectangle(cornerRadius: 3))
                    Text(label)
                        .font(Theme.micro)
                        .foregroundStyle(Theme.inkMuted)
                }
            }
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
        .task(id: model.currentPhotoId) {
            guard let photo = model.photo,
                  loadedFor != photo.id || image == nil else { return }
            image = await ImagePipeline.shared.loupeImage(
                photo: photo, libraryRoot: model.libraryRoot)
            loadedFor = photo.id
            dragOffset = .zero
            panBase = .zero
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
                if model.comparing || model.showExport || model.showSettings {
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
            case "c":
                if model.compareIds.count >= 2 { model.comparing.toggle() }
            default: return false
            }
            return true
        }
    }
}
