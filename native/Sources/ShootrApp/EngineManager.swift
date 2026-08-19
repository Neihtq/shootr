import Foundation

/// Launches and owns the engine subprocess (bundled-app mode).
///
/// Startup: if port 8721 already answers, use that engine (a dev instance
/// run from source — never fight it). Otherwise spawn the bundled one and
/// wait for /api/health. On app quit, terminate only what we spawned.
@MainActor
final class EngineManager {
    static let shared = EngineManager()

    enum State: Equatable {
        case checking
        case starting
        case running(external: Bool)
        case failed(String)
    }

    private(set) var state: State = .checking
    private var process: Process?

    private var healthURL: URL {
        URL(string: "http://127.0.0.1:8721/api/health")!
    }

    /// Bundled engine layout (see make-app.sh --bundled):
    ///   Resources/python/bin/python3     — relocatable Python
    ///   Resources/engine/shootr/…        — engine package
    ///   Resources/shootr-analyze         — Swift helper
    ///   Resources/web-dist/              — built web UI
    private var bundledPython: URL? {
        Bundle.main.resourceURL?
            .appendingPathComponent("python/bin/python3")
    }

    private var bundledEngineDir: URL? {
        Bundle.main.resourceURL?.appendingPathComponent("engine")
    }

    func ensureRunning() async -> State {
        state = .checking
        if await healthy() {
            state = .running(external: true)
            return state
        }
        guard let python = bundledPython, let engineDir = bundledEngineDir,
              FileManager.default.isExecutableFile(atPath: python.path) else {
            state = .failed(
                "engine not running — start it with: python -m shootr.api\n"
                + "(no bundled engine in this build)")
            return state
        }

        state = .starting
        let p = Process()
        p.executableURL = python
        p.arguments = ["-m", "shootr.api"]
        p.currentDirectoryURL = engineDir
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = engineDir.path
        if let helper = Bundle.main.resourceURL?
            .appendingPathComponent("shootr-analyze").path {
            env["SHOOTR_HELPER"] = helper
        }
        p.environment = env
        do {
            try p.run()
        } catch {
            state = .failed("could not launch engine: \(error)")
            return state
        }
        process = p

        // Health-wait: cold start is Python import + DB migrate, ~1-3 s.
        for _ in 0..<40 {
            try? await Task.sleep(for: .milliseconds(250))
            if await healthy() {
                state = .running(external: false)
                return state
            }
            if !p.isRunning {
                state = .failed("engine exited during startup")
                return state
            }
        }
        state = .failed("engine did not become healthy within 10 s")
        return state
    }

    /// Quit hook: stop only what we own. An external dev engine stays up.
    func shutdown() {
        process?.terminate()
        process = nil
    }

    private func healthy() async -> Bool {
        var req = URLRequest(url: healthURL)
        req.timeoutInterval = 1.0
        guard let (_, resp) = try? await URLSession.shared.data(for: req)
        else { return false }
        return (resp as? HTTPURLResponse)?.statusCode == 200
    }
}
