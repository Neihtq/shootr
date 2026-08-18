import AppKit
import CoreImage
import Foundation
import ShootrKit

/// The reason this client exists (design 12 §2): full-res RAW at 100%
/// without HTTP or JPEG re-encode.
///
/// Two image paths, chosen per view:
/// - Grid/filmstrip → HTTP thumbnails from the API (cached, shared with web)
/// - Loupe at 100% → local CIRAWFilter decode of the original file
///
/// The local path uses the DISPLAY decode only (Apple defaults on). This
/// client never computes measurements — a subtly different sharpness
/// implementation here would disagree with the engine (design 12 §2).
@MainActor
final class ImagePipeline {
    static let shared = ImagePipeline()

    private let cache = NSCache<NSString, NSImage>()
    private let api = APIClient()

    private init() {
        cache.totalCostLimit = 2 << 30  // ~2 GB of decoded pixels, evicted by cost
    }

    /// Full-quality image for the loupe. Tries the local file first (only
    /// when the library volume is reachable); degrades to the API's 2048px
    /// thumbnail rather than breaking (design 12 §2).
    func loupeImage(photo: PhotoDetail, libraryRoot: String?) async -> NSImage? {
        let key = "loupe:\(photo.id)" as NSString
        if let hit = cache.object(forKey: key) { return hit }

        if let root = libraryRoot, let rel = photo.relPath {
            let url = URL(fileURLWithPath: root).appendingPathComponent(rel)
            if FileManager.default.isReadableFile(atPath: url.path),
               let img = await decodeLocal(url: url) {
                cache.setObject(img, forKey: key, cost: cost(of: img))
                return img
            }
        }
        // Volume unmounted / non-local: web-equivalent fallback.
        return await fetchThumb(photoId: photo.id, size: 2048, key: key)
    }

    /// Local display-path decode off the main actor.
    private func decodeLocal(url: URL) async -> NSImage? {
        await Task.detached(priority: .userInitiated) {
            guard let decoded = try? decode(url: url, path: .display,
                                            scale: 1.0) else { return nil }
            let ci = decoded.image
            guard let cg = sharedContext.createCGImage(ci, from: ci.extent)
            else { return nil }
            return NSImage(cgImage: cg, size: .zero)
        }.value
    }

    private func fetchThumb(photoId: Int, size: Int,
                            key: NSString) async -> NSImage? {
        let url = api.thumbURL(photoId: photoId, size: size)
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let img = NSImage(data: data) else { return nil }
        cache.setObject(img, forKey: key, cost: cost(of: img))
        return img
    }

    private func cost(of image: NSImage) -> Int {
        Int(image.size.width * image.size.height * 4)
    }

    /// Warm the cache for J/K scrubbing (design 11 §9). ±2 full decodes —
    /// heavier than web thumbnails, so a narrower window; NSCache eviction
    /// bounds the memory. Serialized to avoid GPU contention with the
    /// visible decode.
    private var prefetchTask: Task<Void, Never>?

    func prefetch(photos: [PhotoDetail], libraryRoot: String?) {
        prefetchTask?.cancel()
        prefetchTask = Task { [weak self] in
            for photo in photos {
                if Task.isCancelled { return }
                _ = await self?.loupeImage(photo: photo,
                                           libraryRoot: libraryRoot)
            }
        }
    }
}
