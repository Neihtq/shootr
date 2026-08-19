import SwiftUI

/// Design tokens. One place; views never invent colors or sizes.
///
/// Principles (design 11 §8 + dataviz mark specs):
/// - Neutral, dark, recessive chrome — the photograph is the only loud thing.
///   Chrome never uses saturated color; color is reserved for cull states.
/// - Text wears text tokens (primary/secondary/muted), never a state color;
///   a colored mark BESIDE text carries identity.
/// - Meters: thin (5px), rounded, fill + lighter track of the same hue.
enum Theme {
    // Surfaces — a near-black ramp, warm-neutral so photos read true.
    static let bg = Color(hex: 0x111113)
    static let surface = Color(hex: 0x1A1A1D)
    static let surfaceRaised = Color(hex: 0x232327)
    static let hairline = Color(hex: 0x2E2E33)

    // Text tokens
    static let ink = Color(hex: 0xE8E8EA)
    static let inkSecondary = Color(hex: 0x9A9AA2)
    static let inkMuted = Color(hex: 0x5E5E66)

    // Cull states — the ONLY saturated colors in the app.
    static let pick = Color(hex: 0x4CC38A)
    static let alt = Color(hex: 0x5EA7F7)
    static let reject = Color(hex: 0x4A4A50)
    static let bracket = Color(hex: 0xE5B45B)
    static let override_ = Color(hex: 0xB88CF0)

    // Status — reserved for app state (a job stopped, a drive vanished),
    // never for a cull verdict or a series. Kept distinct from `bracket`
    // so an amber card badge can't be misread as "this is a bracket set",
    // and always paired with words, never color alone.
    static let warning = Color(hex: 0xD99A3E)

    // Meters (evidence bars): one hue, fill + lighter track of the same ramp.
    static let meterFill = Color(hex: 0x8B8B96)
    static let meterTrack = Color(hex: 0x2A2A2F)

    static func stateColor(_ state: String?) -> Color {
        switch state {
        case "pick": return pick
        case "alt": return alt
        case "reject": return reject
        default: return hairline
        }
    }

    // Type scale — system sans, few sizes, weight does the hierarchy.
    static let heading = Font.system(size: 15, weight: .semibold)
    static let body = Font.system(size: 12)
    static let caption = Font.system(size: 11)
    static let micro = Font.system(size: 9.5, weight: .medium)
    static let value = Font.system(size: 11, weight: .medium).monospacedDigit()
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255)
    }
}

/// Small colored square that carries identity beside text (text itself
/// never wears the state color).
struct StateSwatch: View {
    let color: Color
    var body: some View {
        RoundedRectangle(cornerRadius: 2)
            .fill(color)
            .frame(width: 7, height: 7)
    }
}
