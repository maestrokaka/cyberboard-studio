import Cocoa

struct CompanionPalette {
    let light: Bool
    var background: NSColor { light ? NSColor(calibratedRed: 1, green: 0.989, blue: 0.947, alpha: 1) : NSColor(calibratedRed: 0.067, green: 0.071, blue: 0.075, alpha: 1) }
    var border: NSColor { light ? NSColor(calibratedRed: 0.79, green: 0.74, blue: 0.63, alpha: 1) : NSColor(calibratedWhite: 0.28, alpha: 1) }
    var text: NSColor { light ? NSColor(calibratedRed: 0.43, green: 0.31, blue: 0.18, alpha: 1) : NSColor(calibratedWhite: 0.94, alpha: 1) }
    var title: NSColor { light ? NSColor(calibratedRed: 0.49, green: 0.30, blue: 0.15, alpha: 1) : NSColor(calibratedRed: 1, green: 0.58, blue: 0.31, alpha: 1) }
    var accent: NSColor { light ? NSColor(calibratedRed: 0.05, green: 0.72, blue: 0.67, alpha: 1) : NSColor(calibratedRed: 0.96, green: 0.46, blue: 0.22, alpha: 1) }
    var secondary: NSColor { light ? NSColor(calibratedRed: 0.96, green: 0.94, blue: 0.86, alpha: 1) : NSColor(calibratedWhite: 0.16, alpha: 1) }
}

struct CompanionInteractionGate {
    private(set) var zone: String?
    private var entered: TimeInterval = 0
    private var lastGlobal: TimeInterval = -.infinity
    private var lastZones: [String: TimeInterval] = [:]
    private var consumed = false
    mutating func reset() { zone = nil; entered = 0; consumed = false }
    mutating func consume(_ candidate: String?, now: TimeInterval, blocked: Bool) -> String? {
        guard let candidate else { reset(); return nil }
        guard !blocked else { entered = now; return nil }
        if zone != candidate { zone = candidate; entered = now; consumed = false; return nil }
        guard !consumed, now - entered >= 0.48, now - lastGlobal >= 3.2,
              now - (lastZones[candidate] ?? -.infinity) >= 9 else { return nil }
        lastGlobal = now; lastZones[candidate] = now; consumed = true
        return candidate
    }
}

struct CompanionPlacement {
    let frame: NSRect
    let image: NSRect
    let bubble: NSRect
    static func calculate(anchor: NSPoint, size: Double, expanded: Bool, visible: NSRect) -> CompanionPlacement {
        let width = size * 0.5
        let x = min(max(anchor.x, visible.minX), max(visible.minX, visible.maxX - width - 12))
        let y = min(max(anchor.y, visible.minY), max(visible.minY, visible.maxY - size - 12))
        let left = expanded && x + width + 325 > visible.maxX
        let imageX = left ? 325.0 : 0
        return CompanionPlacement(frame: NSRect(x: x - imageX, y: y, width: width + (expanded ? 325 : 12), height: size + 12),
                                  image: NSRect(x: imageX, y: 0, width: width, height: size),
                                  bubble: NSRect(x: left ? 0 : width - 8, y: max(20, size - 184), width: 328, height: 180))
    }
}

final class CompanionStyle {
    let resources: URL
    let catalog: [String: Any]
    private(set) var preferences: [String: Any]
    private var images: [String: NSImage] = [:]
    private var recent: [String] = []
    private let defaults: UserDefaults
    let stateRoot: URL
    init(resources: URL, defaults: UserDefaults = .standard, stateRoot: URL? = nil) {
        self.resources = resources; self.defaults = defaults
        self.stateRoot = stateRoot ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Cyberboard Studio")
        let url = resources.appendingPathComponent("web/assets/companion/catalog.json")
        catalog = (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String: Any] ?? [:]
        let fallback = catalog["defaults"] as? [String: Any] ?? [:]
        preferences = fallback
        if let stored = defaults.dictionary(forKey: "MiaoCall.Companion.v1"), let valid = try? validate(stored) { preferences = valid }
    }
    var resident: Bool { preferences["mode"] as? String == "resident" }
    var soundEnabled: Bool { preferences["sound"] as? Bool == true }
    var outfits: [[String: Any]] { catalog["outfits"] as? [[String: Any]] ?? [] }
    var zones: [[String: Any]] { catalog["zones"] as? [[String: Any]] ?? [] }
    func validCustom(_ id: String) -> Bool {
        id.range(of: "^custom-[0-9a-f]{32}$", options: .regularExpression) != nil &&
        FileManager.default.fileExists(atPath: stateRoot.appendingPathComponent("companion-outfits/" + id + ".png").path)
    }
    func validate(_ candidate: [String: Any]) throws -> [String: Any] {
        guard let mode = candidate["mode"] as? String, ["wake", "resident"].contains(mode),
              let outfit = candidate["outfit"] as? String, outfits.contains(where: { $0["id"] as? String == outfit }) || validCustom(outfit),
              let voice = candidate["voice"] as? String, ["sweet", "mature", "gentle", "playful"].contains(voice),
              let sound = candidate["sound"] as? Bool, let hover = candidate["hover"] as? Bool,
              let volume = candidate["volume"] as? NSNumber, volume.doubleValue.isFinite, (0...1).contains(volume.doubleValue),
              let size = candidate["size"] as? NSNumber, size.doubleValue.isFinite, (240...440).contains(size.doubleValue) else {
            throw NSError(domain: "Companion", code: 1, userInfo: [NSLocalizedDescriptionKey: "桌面陪伴设置无效，请重新选择。"])
        }
        return ["mode": mode, "outfit": outfit, "voice": voice, "sound": sound, "hover": hover,
                "volume": volume.doubleValue, "size": size.doubleValue]
    }
    func save(_ candidate: [String: Any]) throws {
        preferences = try validate(candidate)
        defaults.set(preferences, forKey: "MiaoCall.Companion.v1")
    }
    func picture(_ pose: String = "idle") -> NSImage? {
        let outfit = preferences["outfit"] as? String ?? "sailor-short"
        let key = outfit + "/" + pose
        if let image = images[key] { return image }
        let url: URL
        if validCustom(outfit) { url = stateRoot.appendingPathComponent("companion-outfits/" + outfit + ".png") }
        else {
            let item = outfits.first { $0["id"] as? String == outfit }
            let frames = item?["frames"] as? [String: String] ?? [:]
            url = resources.appendingPathComponent("web/" + (frames[pose] ?? frames["idle"] ?? "assets/miaocall/nekomimi.png"))
        }
        guard let image = NSImage(contentsOf: url) else { return nil }
        images[key] = image; recent.removeAll { $0 == key }; recent.append(key)
        while recent.count > 4 { images.removeValue(forKey: recent.removeFirst()) }
        return image
    }
    func customOutfits() -> [[String: Any]] {
        let folder = stateRoot.appendingPathComponent("companion-outfits")
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.path)) ?? []
        return names.filter { $0.hasSuffix(".png") }.sorted().suffix(20).compactMap { name in
            let identity = String(name.dropLast(4))
            guard name.hasSuffix(".png"), validCustom(identity),
                  let data = try? Data(contentsOf: folder.appendingPathComponent(name)), data.count <= 8 * 1024 * 1024 else { return nil }
            guard let source = NSImage(data: data) else { return nil }
            let thumbnail = NSImage(size: NSSize(width: 100, height: 200))
            thumbnail.lockFocus(); source.draw(in: NSRect(x: 0, y: 0, width: 100, height: 200)); thumbnail.unlockFocus()
            guard let tiff = thumbnail.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
                  let png = bitmap.representation(using: .png, properties: [:]) else { return nil }
            let metadataURL = folder.appendingPathComponent(identity + ".json")
            let metadata = (try? Data(contentsOf: metadataURL)).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            return ["id": identity, "name": "AI 衣装", "builtin": false, "staticPose": true, "hair": metadata?["hair"] as? String ?? "short",
                    "imageDataUrl": "data:image/png;base64," + png.base64EncodedString()]
        }
    }
    func zone(at point: NSPoint) -> [String: Any]? {
        zones.first { zone in
            guard let rect = zone["rect"] as? [Double], rect.count == 4 else { return false }
            return NSRect(x: rect[0], y: rect[1], width: rect[2], height: rect[3]).contains(point)
        }
    }
}

final class CompanionVoice {
    private var clip: NSSound?
    func stop() { clip?.stop(); clip = nil }
    func play(zone: [String: Any], style: CompanionStyle, force: Bool = false, audioSettings: [String: Any]? = nil) {
        guard force || style.soundEnabled else { return }
        stop()
        let settings = audioSettings ?? style.preferences
        let voice = settings["voice"] as? String ?? "sweet"
        let identity = zone["id"] as? String ?? "cheek"
        let url = style.resources.appendingPathComponent("web/assets/companion/audio/\(voice)/\(identity).mp3")
        if let sound = NSSound(contentsOf: url, byReference: false) {
            sound.volume = (settings["volume"] as? NSNumber)?.floatValue ?? 0.45
            clip = sound; sound.play(); return
        }
    }
}
