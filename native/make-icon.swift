import AppKit

// Export the approved PNG; never redraw the keyboard, screen, or paw.
// Only the presentation canvas outside the orange tile becomes transparent.
func approvedArtwork(at url: URL) throws -> NSBitmapImageRep {
    guard let source = NSBitmapImageRep(data: try Data(contentsOf: url)),
          source.bitsPerSample == 8, source.samplesPerPixel == 3,
          !source.isPlanar, let input = source.bitmapData else {
        throw NSError(domain: "CyberboardIcon", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "The approved artwork must be an 8-bit RGB PNG."])
    }
    let width = source.pixelsWide, height = source.pixelsHigh
    let inputStride = source.bitsPerPixel / 8
    guard let result = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
                                       bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                       isPlanar: false, colorSpaceName: .deviceRGB,
                                       bitmapFormat: .alphaNonpremultiplied,
                                       bytesPerRow: width * 4, bitsPerPixel: 32),
          let output = result.bitmapData else {
        throw NSError(domain: "CyberboardIcon", code: 2)
    }
    var retained = 0
    for y in 0..<height {
        var left = width, right = -1
        for x in 0..<width {
            let p = y * source.bytesPerRow + x * inputStride
            let r = Int(input[p]), g = Int(input[p + 1]), b = Int(input[p + 2])
            if r > 150 && r - g > 5 && r - b > 10 {
                left = min(left, x); right = max(right, x)
            }
        }
        // Fill the outer envelope so ivory keyboard details remain opaque.
        for x in 0..<width {
            let p = y * source.bytesPerRow + x * inputStride
            let q = y * result.bytesPerRow + x * 4
            output[q] = input[p]; output[q + 1] = input[p + 1]; output[q + 2] = input[p + 2]
            let inside = x >= left && x <= right
            output[q + 3] = inside ? 255 : 0
            if inside { retained += 1 }
        }
    }
    guard retained > width * height / 2 && retained < width * height else {
        throw NSError(domain: "CyberboardIcon", code: 3,
                      userInfo: [NSLocalizedDescriptionKey: "The orange tile envelope could not be identified."])
    }
    result.size = NSSize(width: width, height: height)
    print("Approved artwork: \(width) × \(height), \(retained) opaque pixels; interior RGB preserved")
    return result
}

func savePNG(_ bitmap: NSBitmapImageRep, to url: URL) throws {
    guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "CyberboardIcon", code: 4)
    }
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try data.write(to: url, options: .atomic)
}

func renderIcon(_ image: NSImage, pixels: Int, to url: URL) throws {
    guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                       bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                       isPlanar: false, colorSpaceName: .deviceRGB,
                                       bytesPerRow: pixels * 4, bitsPerPixel: 32),
          let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        throw NSError(domain: "CyberboardIcon", code: 5)
    }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    context.cgContext.clear(CGRect(x: 0, y: 0, width: pixels, height: pixels))
    image.draw(in: NSRect(x: 0, y: 0, width: pixels, height: pixels), from: .zero,
               operation: .copy, fraction: 1, respectFlipped: false, hints: nil)
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    try savePNG(bitmap, to: url)
}

guard CommandLine.arguments.count == 4 else {
    fputs("Usage: make-icon APPROVED.png OUTPUT.iconset WEB-LOGO.png\n", stderr)
    exit(1)
}
let artwork = try approvedArtwork(at: URL(fileURLWithPath: CommandLine.arguments[1]))
let image = NSImage(size: artwork.size)
image.addRepresentation(artwork)
let output = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
try savePNG(artwork, to: URL(fileURLWithPath: CommandLine.arguments[3]))
for size in [16, 32, 128, 256, 512] {
    try renderIcon(image, pixels: size, to: output.appendingPathComponent("icon_\(size)x\(size).png"))
    try renderIcon(image, pixels: size * 2, to: output.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
print("Icon artwork: \(output.path)")
