// swift-tools-version:6.1
import PackageDescription

// Native culling client (design 12). Scope is deliberately a SUBSET of the
// web app: shoot list, group review, evidence, compare, keyboard culling.
// No library setup, no catalog import, no weight tuning — the web app stays
// the control panel; this is a culling instrument (design 12 §3).
let package = Package(
    name: "ShootrApp",
    platforms: [.macOS(.v15)],
    dependencies: [
        // Shares the decode code with the analysis helper — one Swift
        // package for CIRAWFilter, never forked (design 12 §5).
        .package(path: "../helper"),
    ],
    targets: [
        .executableTarget(
            name: "ShootrApp",
            dependencies: [
                .product(name: "ShootrKit", package: "helper"),
            ],
            swiftSettings: [.unsafeFlags(["-parse-as-library"])]
        ),
    ]
)
