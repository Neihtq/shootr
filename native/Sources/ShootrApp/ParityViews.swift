import SwiftUI

// MARK: - Export dialog (design 11 §7 / 07 §3)
//
// Wraps the engine's safety protocol: preview first, exact diff shown, no
// default-yes on the destructive option. The client only renders the
// engine's diff — it never decides what counts as a conflict (design 10 §2).

struct ExportSheet: View {
    let selectionId: Int
    let api = APIClient()
    @Environment(\.dismiss) private var dismiss

    @State private var preview: APIClient.ExportPreview?
    @State private var result: String?
    @State private var error: String?
    @State private var writing = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Export selects to XMP")
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)

            if let error {
                Text(error).font(Theme.caption).foregroundStyle(.red)
            } else if let result {
                resultView(result)
            } else if let p = preview {
                previewView(p)
            } else {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text("Computing diff…")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
        }
        .padding(18)
        .frame(width: 460)
        .background(Theme.surface)
        .task {
            do {
                preview = try await api.exportPreview(
                    selectionId: selectionId)
            } catch {
                self.error = String(describing: error)
            }
        }
    }

    @ViewBuilder
    private func previewView(_ p: APIClient.ExportPreview) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            DiffLine(icon: "plus.circle", text: "\(p.newSidecars) new sidecars")
            if p.updates > 0 {
                DiffLine(icon: "pencil.circle",
                         text: "\(p.updates) sidecars updated (no develop settings)")
            }
            if !p.conflicts.isEmpty {
                DiffLine(icon: "exclamationmark.triangle",
                         text: "\(p.conflicts.count) existing sidecars WITH develop settings — requires explicit confirmation",
                         tint: Theme.bracket)
            }
            if !p.skippedDng.isEmpty {
                DiffLine(icon: "info.circle",
                         text: "\(p.skippedDng.count) DNG files will be skipped (sidecar writeback unsupported)")
            }
            if p.unchanged > 0 {
                DiffLine(icon: "equal.circle", text: "\(p.unchanged) unchanged")
            }
            Text("Backups → \(p.backupDir)")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
                .padding(.top, 2)
        }

        HStack {
            Spacer()
            Button("Cancel") { dismiss() }
            Button(p.conflicts.isEmpty ? "Write" : "Skip conflicts") {
                run(confirm: false)
            }
            .disabled(writing)
            if !p.conflicts.isEmpty {
                // The destructive option is explicit and never the default.
                Button("Overwrite \(p.conflicts.count) (backed up)") {
                    run(confirm: true)
                }
                .disabled(writing)
                .tint(Theme.bracket)
            }
        }
    }

    @ViewBuilder
    private func resultView(_ text: String) -> some View {
        Text(text).font(Theme.body).foregroundStyle(Theme.ink)
        Text("In Lightroom: select the photos, then Metadata → Read Metadata "
             + "from Files. Note: that step overwrites catalog metadata from "
             + "the files — LrC's behavior, not ours.")
            .font(Theme.caption)
            .foregroundStyle(Theme.inkSecondary)
        HStack {
            Spacer()
            Button("Done") { dismiss() }
        }
    }

    private func run(confirm: Bool) {
        writing = true
        Task {
            do {
                let r = try await api.export(
                    selectionId: selectionId, confirmOverwrite: confirm)
                result = "Wrote \(r.written) sidecars."
            } catch {
                self.error = String(describing: error)
            }
            writing = false
        }
    }
}

struct DiffLine: View {
    let icon: String
    let text: String
    var tint: Color = Theme.inkSecondary

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 11))
                .foregroundStyle(tint)
            Text(text)
                .font(Theme.caption)
                .foregroundStyle(Theme.inkSecondary)
        }
    }
}

// MARK: - Compare view (design 11 §4): synced pan/zoom, the decisive check

struct CompareSheet: View {
    let photoIds: [Int]
    @Bindable var model: ReviewModel
    @Environment(\.dismiss) private var dismiss

    // One shared transform drives every pane (§11.4: same magnification on
    // the same feature, or the comparison is meaningless).
    @State private var zoomed = true
    @State private var pan: CGSize = .zero
    @State private var panBase: CGSize = .zero

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Text("Compare · \(photoIds.count) frames")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
                Text("drag to pan (synced) · Z 100%/fit · Esc close")
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkMuted)
                Spacer()
                Button("Close") { dismiss() }
                    .font(Theme.caption)
            }
            .padding(10)
            .background(Theme.surface)

            GeometryReader { geo in
                let cols = min(photoIds.count, 2)
                let rows = (photoIds.count + 1) / 2
                let paneW = geo.size.width / CGFloat(cols)
                let paneH = geo.size.height / CGFloat(rows)
                LazyVGrid(
                    columns: Array(repeating: GridItem(.flexible(), spacing: 1),
                                   count: cols),
                    spacing: 1
                ) {
                    ForEach(photoIds, id: \.self) { pid in
                        ComparePane(
                            photoId: pid, model: model, zoomed: zoomed,
                            pan: $pan, panBase: $panBase)
                            .frame(width: paneW - 1, height: paneH - 1)
                            .clipped()
                    }
                }
            }
        }
        .frame(minWidth: 900, minHeight: 600)
        .background(Theme.bg)
        .onKeyPress("z") {
            zoomed.toggle()
            pan = .zero
            panBase = .zero
            return .handled
        }
    }
}

struct ComparePane: View {
    let photoId: Int
    @Bindable var model: ReviewModel
    let zoomed: Bool
    @Binding var pan: CGSize
    @Binding var panBase: CGSize

    @State private var image: NSImage?
    @State private var photo: PhotoDetail?

    var body: some View {
        ZStack {
            Color.black
            if let image {
                if zoomed {
                    zoomedImage(image)
                } else {
                    Image(nsImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                }
            } else {
                ProgressView().controlSize(.small)
            }
            overlayInfo
        }
        .task {
            photo = try? await model.api.photo(photoId)
            if let photo {
                image = await ImagePipeline.shared.loupeImage(
                    photo: photo, libraryRoot: model.libraryRoot)
            }
        }
    }

    private var overlayInfo: some View {
        VStack {
            HStack {
                if let p = photo {
                    HStack(spacing: 5) {
                        if let sel = p.selection {
                            StateSwatch(color: Theme.stateColor(sel.state))
                            Text(sel.state.uppercased())
                                .font(Theme.micro)
                                .foregroundStyle(Theme.inkSecondary)
                        }
                        Text(p.filename)
                            .font(Theme.micro)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    .padding(.horizontal, 6)
                    .padding(.vertical, 3)
                    .background(.black.opacity(0.65), in: Capsule())
                }
                Spacer()
            }
            Spacer()
        }
        .padding(6)
    }

    private func zoomedImage(_ img: NSImage) -> some View {
        let px = img.representations.first.map {
            CGSize(width: $0.pixelsWide, height: $0.pixelsHigh)
        } ?? img.size
        var cx = 0.5, cy = 0.5
        if let f = photo?.faces.first, f.bbox.count == 4 {
            cx = f.bbox[0] + f.bbox[2] / 2
            cy = 1 - (f.bbox[1] + f.bbox[3] / 2)
        }
        // The SHARED pan binding: dragging any pane moves all panes.
        let offset = CGSize(
            width: (0.5 - cx) * px.width + pan.width,
            height: (0.5 - cy) * px.height + pan.height)
        return Image(nsImage: img)
            .resizable()
            .frame(width: px.width, height: px.height)
            .offset(offset)
            .gesture(
                DragGesture()
                    .onChanged { v in
                        pan = CGSize(
                            width: panBase.width + v.translation.width,
                            height: panBase.height + v.translation.height)
                    }
                    .onEnded { _ in panBase = pan })
    }
}

// MARK: - Sharpness overlay (design 11 §3): where did focus land?

struct SharpnessOverlay: View {
    let photoId: Int
    @State private var map: APIClient.SharpnessMap?

    var body: some View {
        GeometryReader { geo in
            if let tiles = map?.tiles, let maxV = map?.max, maxV > 0 {
                let rows = tiles.count
                let cols = tiles.first?.count ?? 0
                let w = geo.size.width / CGFloat(cols)
                let h = geo.size.height / CGFloat(rows)
                ForEach(0..<rows, id: \.self) { y in
                    ForEach(0..<cols, id: \.self) { x in
                        Rectangle()
                            .fill(Color(hex: 0xFF5028).opacity(
                                min(0.6, tiles[y][x] / maxV * 0.6)))
                            .frame(width: w, height: h)
                            // Vision origin bottom-left → flip rows.
                            .position(
                                x: (CGFloat(x) + 0.5) * w,
                                y: (CGFloat(rows - 1 - y) + 0.5) * h)
                    }
                }
            }
        }
        .allowsHitTesting(false)
        .task(id: photoId) {
            map = try? await APIClient().sharpnessMap(photoId: photoId)
        }
    }
}

// MARK: - Eye overlay (design 11 §3): who is blinking?

/// A marker on EVERY face's eye region with that face's eyes-open value —
/// in place, so a group shot answers "who blinked" at a glance. Color +
/// number, never color alone: green ≥ open boundary, amber in the partial-
/// blink band, red below the "eyes closed" cut (matches the calibrated
/// culling boundary, design 04 §2.2); gray "—" = detector abstained.
struct EyeOverlay: View {
    let photo: PhotoDetail

    var body: some View {
        GeometryReader { geo in
            if photo.faces.isEmpty {
                Text("no face detected")
                    .font(Theme.micro)
                    .foregroundStyle(Theme.inkSecondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(.black.opacity(0.72), in: Capsule())
                    .frame(maxWidth: .infinity, maxHeight: .infinity,
                           alignment: .bottomTrailing)
                    .padding(10)
            }
            ForEach(photo.faces, id: \.idx) { f in
                if f.bbox.count == 4 {
                    // Eye band: upper part of the face box (55–100% of its
                    // height — same heuristic as the eye-crop endpoint;
                    // landmarks aren't persisted in M1). Vision origin is
                    // bottom-left; SwiftUI top-left.
                    let x = f.bbox[0] * geo.size.width
                    let w = f.bbox[2] * geo.size.width
                    let bandH = f.bbox[3] * 0.45 * geo.size.height
                    let y = (1 - f.bbox[1] - f.bbox[3]) * geo.size.height
                    let open = worstOpen(f)
                    let color = openColor(open)

                    RoundedRectangle(cornerRadius: 3)
                        .stroke(color, lineWidth: 1.5)
                        .frame(width: w, height: bandH)
                        .position(x: x + w / 2, y: y + bandH / 2)
                    // Score chip pinned above the band.
                    HStack(spacing: 3) {
                        StateSwatch(color: color)
                        Text(open.map { String(format: "%.2f", $0) } ?? "—")
                            .font(Theme.micro)
                            .foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 5)
                    .padding(.vertical, 2)
                    .background(.black.opacity(0.72), in: Capsule())
                    .position(x: x + w / 2, y: max(9, y - 11))
                }
            }
        }
        .allowsHitTesting(false)
    }

    /// min of the two eyes — one closed eye is a blink (design 04 §2.2).
    private func worstOpen(_ f: FaceInfo) -> Double? {
        let vals = ["left", "right"].compactMap { f.eyes[$0]?.open }
        return vals.min()
    }

    private func openColor(_ open: Double?) -> Color {
        guard let open else { return Theme.inkMuted }  // abstained ≠ bad
        if open < 0.42 { return Color(hex: 0xE5484D) }  // eyes closed
        if open < 0.65 { return Theme.bracket }         // partial blink
        return Theme.pick                               // open
    }
}

// MARK: - Composition overlay (design 11 §3): is this flag fair?

struct CompositionOverlay: View {
    let photo: PhotoDetail

    var body: some View {
        GeometryReader { geo in
            // Rule-of-thirds grid
            Path { p in
                for i in 1...2 {
                    let x = geo.size.width * CGFloat(i) / 3
                    let y = geo.size.height * CGFloat(i) / 3
                    p.move(to: CGPoint(x: x, y: 0))
                    p.addLine(to: CGPoint(x: x, y: geo.size.height))
                    p.move(to: CGPoint(x: 0, y: y))
                    p.addLine(to: CGPoint(x: geo.size.width, y: y))
                }
            }
            .stroke(.white.opacity(0.25), lineWidth: 1)

            // Face boxes — Vision origin is bottom-left; SwiftUI top-left.
            ForEach(photo.faces, id: \.idx) { f in
                if f.bbox.count == 4 {
                    let x = f.bbox[0] * geo.size.width
                    let w = f.bbox[2] * geo.size.width
                    let h = f.bbox[3] * geo.size.height
                    let y = (1 - f.bbox[1] - f.bbox[3]) * geo.size.height
                    Rectangle()
                        .stroke(Theme.bracket.opacity(0.7), lineWidth: 1)
                        .frame(width: w, height: h)
                        .position(x: x + w / 2, y: y + h / 2)
                    Text("face \(f.idx)")
                        .font(Theme.micro)
                        .foregroundStyle(Theme.bracket.opacity(0.9))
                        .position(x: x + 20, y: max(6, y - 8))
                }
            }
        }
        .allowsHitTesting(false)
    }
}

/// Sizes overlay content to the letterboxed area a `.fit` image occupies —
/// a heatmap over the whole container would misalign with the pixels.
struct FittedOverlay<Content: View>: View {
    let imageSize: CGSize
    @ViewBuilder let content: () -> Content

    var body: some View {
        GeometryReader { geo in
            let scale = min(geo.size.width / max(imageSize.width, 1),
                            geo.size.height / max(imageSize.height, 1))
            let w = imageSize.width * scale
            let h = imageSize.height * scale
            content()
                .frame(width: w, height: h)
                .position(x: geo.size.width / 2, y: geo.size.height / 2)
        }
    }
}

// MARK: - Shoot settings (rename / profile switch = instant rescore)

struct ShootSettingsSheet: View {
    @Bindable var model: ReviewModel
    @Environment(\.dismiss) private var dismiss

    @State private var name: String = ""
    @State private var profile: String = "event"
    @State private var status: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Shoot settings")
                .font(Theme.heading)
                .foregroundStyle(Theme.ink)
            TextField("Name", text: $name)
                .textFieldStyle(.roundedBorder)
            Picker("Genre", selection: $profile) {
                ForEach(["portrait", "event", "landscape", "street"],
                        id: \.self) { Text($0) }
            }
            Text("Changing the genre rescores instantly — no re-analysis.")
                .font(Theme.micro)
                .foregroundStyle(Theme.inkMuted)
            if let status {
                Text(status)
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
            }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Apply") { apply() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(18)
        .frame(width: 360)
        .background(Theme.surface)
        .onAppear {
            name = model.shoot?.name ?? ""
            profile = model.shoot?.profile ?? "event"
        }
    }

    private func apply() {
        guard let shoot = model.shoot else { return }
        Task {
            do {
                let r = try await model.api.patchShoot(
                    shoot.id,
                    name: name != shoot.name ? name : nil,
                    profile: profile != shoot.profile ? profile : nil)
                status = r.rescored > 0
                    ? "rescored \(r.rescored) photos" : nil
                // Rescoring changes ranks; regenerate view state.
                await model.loadHome()
                if let updated = model.shoots.first(where: { $0.id == shoot.id }) {
                    await model.open(shoot: updated)
                }
                dismiss()
            } catch {
                status = String(describing: error)
            }
        }
    }
}
