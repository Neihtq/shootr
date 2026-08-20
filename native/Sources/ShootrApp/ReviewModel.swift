import Foundation
import Observation

/// View state for group review. All domain values come from the API;
/// this holds only navigation position and fetched data.
@MainActor
@Observable
final class ReviewModel {
    let api = APIClient()

    var shoots: [Shoot] = []
    var libraries: [Library] = []
    var errorMessage: String?

    // Current review context
    var shoot: Shoot?
    var groups: [PhotoGroup] = []
    var selection: Selection?
    var groupIndex = 0
    var frameIndex = 0
    var photo: PhotoDetail?
    var showEvidence = true
    /// Z (design 11 §5): loupe at 100% pixels vs fit. The loupe view centers
    /// on the primary face when zoomed.
    var zoomed = false
    var showSharpness = false  // S — 16×16 heatmap overlay
    var showComposition = false  // O — face boxes + thirds grid
    var showEyes = false  // B — full-res eye crops (blink check)
    var comparing = false  // C — synced compare sheet
    var showExport = false
    var showSettings = false
    /// ? — the shortcut list. Discoverable in-app rather than README-only:
    /// an overlay the user can't name (the S heatmap) is an overlay they
    /// won't trust.
    var showShortcuts = false

    /// Compare the current frame against the group's top-ranked others
    /// (the pick-vs-alt judgement, design 11 §4).
    var compareIds: [Int] {
        guard let g = currentGroup, let pid = currentPhotoId else { return [] }
        let ranked = g.photoIds
            .filter { $0 != pid }
            .sorted { (entryByPhoto[$0]?.rank ?? 99)
                < (entryByPhoto[$1]?.rank ?? 99) }
        return [pid] + ranked.prefix(3)
    }

    var entryByPhoto: [Int: SelectionEntry] {
        Dictionary(uniqueKeysWithValues:
            (selection?.entries ?? []).map { ($0.photoId, $0) })
    }

    var currentGroup: PhotoGroup? {
        groups.indices.contains(groupIndex) ? groups[groupIndex] : nil
    }

    var currentPhotoId: Int? {
        guard let g = currentGroup,
              g.photoIds.indices.contains(frameIndex) else { return nil }
        return g.photoIds[frameIndex]
    }

    var libraryRoot: String? {
        libraries.first(where: \.online)?.rootPath
    }

    var proposals: [APIClient.Proposal] = []
    var proposalsFor: Int?  // library id the proposals belong to
    var analyzeStatus: String?
    /// Determinate progress for the running analyze job, rendered as a bar
    /// on the shoot card being analyzed.
    var analyzeProgress: (completed: Int, total: Int)?
    var analyzingShootId: Int?

    func loadHome() async {
        do {
            shoots = try await api.shoots()
            libraries = try await api.libraries()
            // Adopt a job already running in the engine — started before a
            // relaunch, or by the web UI. Without this the card would stay
            // locked until something else refreshed the list.
            if analyzingShootId == nil,
               let busy = shoots.first(where: \.isBusy),
               let jobId = busy.busyJobId {
                analyzingShootId = busy.id
                analyzeProgress = (busy.analyzedCount, busy.photoCount)
                analyzeStatus = "analyzing…"
                Task { await self.watchJob(jobId) }
            }
            // Surface pending proposals for the first library that has any.
            proposals = []
            proposalsFor = nil
            for lib in libraries where lib.online {
                let p = (try? await api.proposals(libraryId: lib.id)) ?? []
                if !p.isEmpty {
                    proposals = p
                    proposalsFor = lib.id
                    break
                }
            }
            errorMessage = nil
        } catch {
            errorMessage = String(describing: error)
        }
    }

    func addLibrary(path: String) async {
        // Scanning is synchronous and can take seconds on a large folder;
        // without this the window looks frozen and nothing explains why.
        analyzeStatus = "scanning \((path as NSString).lastPathComponent)…"
        defer { analyzeStatus = nil }
        do {
            let r = try await api.addLibrary(rootPath: path)
            await loadHome()
            if r.scan.added == 0 && r.scan.unchanged == 0 {
                errorMessage = "No photos found in \(path) — "
                    + "checked for RAW (CR2/CR3/ARW/RAF) and JPEG files."
            } else {
                errorMessage = nil
            }
        } catch {
            errorMessage = String(describing: error)
        }
    }

    func removeLibrary(_ id: Int) async {
        do {
            _ = try await api.deleteLibrary(id)
            await loadHome()
        } catch {
            errorMessage = String(describing: error)
        }
    }

    func confirmProposal(_ p: APIClient.Proposal, name: String,
                         profile: String) async {
        guard let libId = proposalsFor else { return }
        do {
            let shoot = try await api.createShoot(
                libraryId: libId, name: name, profile: profile,
                photoIds: p.photoIds)
            // Kick off analysis immediately; the engine chains
            // group → score → select when it completes.
            let job = try await api.analyze(shootId: shoot.id)
            if job.total > 0 {
                analyzeStatus = "analyzing…"
                analyzingShootId = shoot.id
                analyzeProgress = (0, job.total)
            }
            await loadHome()
            if job.total > 0 {
                Task { await self.watchJob(job.jobId) }
            }
        } catch {
            errorMessage = String(describing: error)
        }
    }

    /// "Analyze & cull" on an existing shoot. Also the re-run path: photos
    /// already analyzed are skipped (the engine only queues un-analyzed
    /// ones), and the derived steps re-run either way.
    func analyzeShoot(_ shoot: Shoot) async {
        do {
            let job = try await api.analyze(shootId: shoot.id)
            if job.total > 0 {
                analyzeStatus = "analyzing…"
                analyzingShootId = shoot.id
                analyzeProgress = (0, job.total)
                Task { await self.watchJob(job.jobId) }
            } else {
                // Everything analyzed: engine chained group/score/select
                // inline and it completed in milliseconds. Without visible
                // feedback a fast success reads as a dead button — so open
                // the shoot on the fresh selection.
                analyzeStatus = "re-culled ✓"
                await loadHome()
                if let updated = shoots.first(where: { $0.id == shoot.id }) {
                    await open(shoot: updated)
                }
                Task {
                    try? await Task.sleep(for: .seconds(3))
                    if analyzeStatus == "re-culled ✓" { analyzeStatus = nil }
                }
            }
        } catch {
            errorMessage = String(describing: error)
        }
    }

    /// Job ids already being polled — `loadHome()` adopts running jobs, and
    /// `watchJob` calls it, so without this a single job could accumulate
    /// watchers on every refresh.
    private var watchedJobs: Set<Int> = []

    private func watchJob(_ jobId: Int) async {
        guard watchedJobs.insert(jobId).inserted else { return }
        defer { watchedJobs.remove(jobId) }
        while true {
            try? await Task.sleep(for: .seconds(1))
            guard let s = try? await api.jobStatus(jobId) else { continue }
            if s.state == "done" || s.state == "failed" {
                analyzeStatus = s.failed > 0
                    ? "analysis finished — \(s.failed) files failed" : nil
                analyzeProgress = nil
                analyzingShootId = nil
                await loadHome()
                return
            }
            analyzeProgress = (s.completed, s.total)
            analyzeStatus = "analyzing \(s.completed)/\(s.total)"
        }
    }

    func open(shoot: Shoot) async {
        self.shoot = shoot
        groupIndex = 0
        frameIndex = 0
        do {
            groups = try await api.groups(shootId: shoot.id)
            if let selId = shoot.latestSelectionId {
                selection = try await api.selection(selId)
            } else {
                selection = nil
            }
            await refreshPhoto()
            errorMessage = nil
            warmLeadingGroups()
        } catch {
            errorMessage = String(describing: error)
        }
    }

    /// Entering a shoot is the coldest moment: nothing is prefetched yet,
    /// and skimming ↓ through the sidebar hits one cache miss per group.
    private func warmLeadingGroups() {
        warmGroupWindow()
    }

    /// Rolling warm-ahead window: the first frame of the next groups from
    /// the CURRENT position — a fixed lead-in only helped the first dozen,
    /// and skimming past it went cold again (user-reported). The window
    /// follows the cursor; the server caches by content, so re-requests
    /// are free and one background task at a time is plenty.
    private var warmTask: Task<Void, Never>?

    private func warmGroupWindow() {
        let ahead = groups.dropFirst(groupIndex + 1).prefix(20)
        let behind = groups.prefix(groupIndex).suffix(3)
        let firsts = (Array(ahead) + Array(behind))
            .compactMap(\.photoIds.first)
        guard !firsts.isEmpty else { return }
        warmTask?.cancel()
        warmTask = Task.detached(priority: .background) {
            for pid in firsts {
                if Task.isCancelled { return }
                let url = APIClient().thumbURL(photoId: pid, size: 2048)
                _ = try? await URLSession.shared.data(from: url)
            }
        }
    }

    func refreshPhoto() async {
        guard let pid = currentPhotoId else {
            photo = nil
            return
        }
        // Stale-response guard: holding J down issues overlapping fetches and
        // they can complete out of order, leaving the evidence panel and
        // action bar describing a frame the user already moved past. Drop any
        // response that is no longer the current frame.
        let fetched = try? await api.photo(pid)
        guard currentPhotoId == pid else { return }
        photo = fetched
        prefetchNeighbors()
    }

    /// Warm the loupe cache for the frames J/K will land on next — plus the
    /// first frame of the adjacent groups, because ↑/↓ skimming always
    /// lands there and a cold group otherwise stares at a decode.
    private func prefetchNeighbors() {
        guard let g = currentGroup else { return }
        var candidates = [frameIndex + 1, frameIndex - 1,
                          frameIndex + 2, frameIndex - 2]
            .filter { g.photoIds.indices.contains($0) }
            .map { g.photoIds[$0] }
        for gi in [groupIndex + 1, groupIndex - 1]
        where groups.indices.contains(gi) {
            if let first = groups[gi].photoIds.first {
                candidates.append(first)
            }
        }
        warmGroupWindow()
        guard !candidates.isEmpty else { return }
        Task {
            var details: [PhotoDetail] = []
            for pid in candidates {
                if let d = try? await api.photo(pid) { details.append(d) }
            }
            ImagePipeline.shared.prefetch(photos: details,
                                          libraryRoot: libraryRoot)
        }
    }

    // MARK: navigation — identical keybindings to the web client (§12.4)

    func nextFrame() async {
        guard let g = currentGroup else { return }
        frameIndex = min(g.photoIds.count - 1, frameIndex + 1)
        await refreshPhoto()
    }

    func prevFrame() async {
        frameIndex = max(0, frameIndex - 1)
        await refreshPhoto()
    }

    func nextGroup() async {
        groupIndex = min(groups.count - 1, groupIndex + 1)
        frameIndex = 0
        await refreshPhoto()
    }

    func prevGroup() async {
        groupIndex = max(0, groupIndex - 1)
        frameIndex = 0
        await refreshPhoto()
    }

    func firstFrame() async {
        frameIndex = 0
        await refreshPhoto()
    }

    func lastFrame() async {
        guard let g = currentGroup else { return }
        frameIndex = g.photoIds.count - 1
        await refreshPhoto()
    }

    func setState(_ state: String) async {
        guard let selId = shoot?.latestSelectionId,
              let pid = currentPhotoId,
              currentGroup?.isBracket != true  // brackets: no cull controls
        else { return }
        do {
            _ = try await api.override(selectionId: selId, photoId: pid,
                                       state: state)
            selection = try await api.selection(selId)
            await refreshPhoto()
        } catch {
            errorMessage = String(describing: error)
        }
    }

    /// Space (design 11 §5): toggle pick ↔ reject on the current frame.
    func togglePick() async {
        let current = entryByPhoto[currentPhotoId ?? -1]?.state
        await setState(current == "pick" ? "reject" : "pick")
    }
}
