// swift-tools-version:6.1
import PackageDescription

let package = Package(
    name: "shootr-analyze",
    platforms: [.macOS(.v15)],
    products: [
        // Consumed by the native client (design 12 §2) — decode code is
        // shared, never forked.
        .library(name: "ShootrKit", targets: ["ShootrKit"]),
    ],
    targets: [
        // Library target so the SwiftUI client (M4) can share the decode
        // code without forking it (design 12 §5).
        .target(name: "ShootrKit"),
        .executableTarget(
            name: "shootr-analyze",
            dependencies: ["ShootrKit"]
        ),
        // No .testTarget: neither swift-testing nor XCTest is available with
        // CLI-tools-only (SPEC §1). Unit checks live in the `selftest`
        // subcommand, driven by pytest alongside the engine suite.
    ]
)
