import AppKit
import SwiftUI

@main
struct ShootrApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup("Shootr") {
            EngineGate()
        }
    }
}

/// Terminate the engine we spawned when the app quits.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillTerminate(_ notification: Notification) {
        // Synchronous: a deferred Task never runs — the process exits
        // first and the engine would be orphaned (observed in smoke test).
        MainActor.assumeIsolated {
            EngineManager.shared.shutdown()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(
        _ sender: NSApplication) -> Bool { true }
}

/// Shows engine startup state, then the app. The URL line doubles as the
/// pointer to the engine-served web UI.
struct EngineGate: View {
    @State private var state: EngineManager.State = .checking

    var body: some View {
        Group {
            switch state {
            case .checking, .starting:
                VStack(spacing: 10) {
                    ProgressView()
                    Text(state == .checking ? "Looking for engine…"
                         : "Starting engine…")
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                }
                .frame(minWidth: 520, minHeight: 440)
                .background(Theme.bg)
            case .failed(let message):
                VStack(spacing: 10) {
                    Image(systemName: "bolt.horizontal.circle")
                        .font(.system(size: 28))
                        .foregroundStyle(Theme.inkMuted)
                    Text(message)
                        .font(Theme.caption)
                        .foregroundStyle(Theme.inkSecondary)
                        .multilineTextAlignment(.center)
                    Button("Retry") {
                        Task { state = await EngineManager.shared.ensureRunning() }
                    }
                }
                .padding(30)
                .frame(minWidth: 520, minHeight: 440)
                .background(Theme.bg)
            case .running:
                RootView()
            }
        }
        .task {
            state = await EngineManager.shared.ensureRunning()
        }
    }
}
