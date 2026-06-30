#pragma once

#include "../core/types.hpp"
#include "../core/static_string.hpp"
#include "../core/file_handle.hpp"
#include <vector>
#include <cstring>

namespace output_module::generators {

using namespace core;

// Simple TIFF writer for uncompressed RGB images
class TifGenerator {
private:
    static constexpr uint16_t TIFF_MAGIC_LE = 0x4949;  // Little-endian
    static constexpr uint16_t TIFF_VERSION = 42;

    // TIFF tag IDs
    static constexpr uint16_t TAG_IMAGE_WIDTH = 256;
    static constexpr uint16_t TAG_IMAGE_HEIGHT = 257;
    static constexpr uint16_t TAG_BITS_PER_SAMPLE = 258;
    static constexpr uint16_t TAG_COMPRESSION = 259;
    static constexpr uint16_t TAG_PHOTOMETRIC = 262;
    static constexpr uint16_t TAG_STRIP_OFFSETS = 273;
    static constexpr uint16_t TAG_SAMPLES_PER_PIXEL = 277;
    static constexpr uint16_t TAG_ROWS_PER_STRIP = 278;
    static constexpr uint16_t TAG_STRIP_BYTE_COUNTS = 279;
    static constexpr uint16_t TAG_X_RESOLUTION = 282;
    static constexpr uint16_t TAG_Y_RESOLUTION = 283;
    static constexpr uint16_t TAG_RESOLUTION_UNIT = 296;

    // TIFF constants
    static constexpr uint16_t COMPRESSION_NONE = 1;
    static constexpr uint16_t PHOTOMETRIC_RGB = 2;
    static constexpr uint16_t RESOLUTION_INCH = 2;

    // TIFF types
    static constexpr uint16_t TYPE_SHORT = 3;
    static constexpr uint16_t TYPE_LONG = 4;
    static constexpr uint16_t TYPE_RATIONAL = 5;

    struct TiffHeader {
        uint16_t byteOrder;
        uint16_t version;
        uint32_t ifdOffset;
    } __attribute__((packed));

    struct IfdEntry {
        uint16_t tag;
        uint16_t type;
        uint32_t count;
        uint32_t valueOffset;
    } __attribute__((packed));

    static void writeLE16(std::vector<uint8_t>& buf, uint16_t val) {
        buf.push_back(val & 0xFF);
        buf.push_back((val >> 8) & 0xFF);
    }

    static void writeLE32(std::vector<uint8_t>& buf, uint32_t val) {
        buf.push_back(val & 0xFF);
        buf.push_back((val >> 8) & 0xFF);
        buf.push_back((val >> 16) & 0xFF);
        buf.push_back((val >> 24) & 0xFF);
    }

public:
    TifGenerator() = default;

    // Save RGB image data as TIFF file
    // data: RGB pixel data (3 bytes per pixel)
    // width, height: image dimensions
    // dpi: resolution (default 100)
    template<SizeType PathSize>
    [[nodiscard]] bool save(
        const uint8_t* data,
        uint32_t width,
        uint32_t height,
        const StaticString<PathSize>& outputPath,
        uint32_t dpi = 100
    ) noexcept {
        if (!data || width == 0 || height == 0) {
            return false;
        }

        std::vector<uint8_t> buffer;
        buffer.reserve(8 + 2 + 12 * 12 + 4 + 16 + width * height * 3);

        // TIFF Header
        writeLE16(buffer, TIFF_MAGIC_LE);
        writeLE16(buffer, TIFF_VERSION);
        writeLE32(buffer, 8);  // IFD offset right after header

        // Calculate offsets
        uint32_t numTags = 12;
        uint32_t ifdSize = 2 + numTags * 12 + 4;  // count + entries + next IFD
        uint32_t bitsPerSampleOffset = 8 + ifdSize;
        uint32_t xResOffset = bitsPerSampleOffset + 6;  // 3 shorts
        uint32_t yResOffset = xResOffset + 8;  // rational = 8 bytes
        uint32_t stripOffset = yResOffset + 8;
        uint32_t stripByteCount = width * height * 3;

        // IFD entry count
        writeLE16(buffer, numTags);

        // IFD entries (must be sorted by tag)
        // 256: ImageWidth
        writeLE16(buffer, TAG_IMAGE_WIDTH);
        writeLE16(buffer, TYPE_LONG);
        writeLE32(buffer, 1);
        writeLE32(buffer, width);

        // 257: ImageHeight
        writeLE16(buffer, TAG_IMAGE_HEIGHT);
        writeLE16(buffer, TYPE_LONG);
        writeLE32(buffer, 1);
        writeLE32(buffer, height);

        // 258: BitsPerSample (3 values: 8,8,8)
        writeLE16(buffer, TAG_BITS_PER_SAMPLE);
        writeLE16(buffer, TYPE_SHORT);
        writeLE32(buffer, 3);
        writeLE32(buffer, bitsPerSampleOffset);

        // 259: Compression
        writeLE16(buffer, TAG_COMPRESSION);
        writeLE16(buffer, TYPE_SHORT);
        writeLE32(buffer, 1);
        writeLE32(buffer, COMPRESSION_NONE);

        // 262: PhotometricInterpretation
        writeLE16(buffer, TAG_PHOTOMETRIC);
        writeLE16(buffer, TYPE_SHORT);
        writeLE32(buffer, 1);
        writeLE32(buffer, PHOTOMETRIC_RGB);

        // 273: StripOffsets
        writeLE16(buffer, TAG_STRIP_OFFSETS);
        writeLE16(buffer, TYPE_LONG);
        writeLE32(buffer, 1);
        writeLE32(buffer, stripOffset);

        // 277: SamplesPerPixel
        writeLE16(buffer, TAG_SAMPLES_PER_PIXEL);
        writeLE16(buffer, TYPE_SHORT);
        writeLE32(buffer, 1);
        writeLE32(buffer, 3);

        // 278: RowsPerStrip
        writeLE16(buffer, TAG_ROWS_PER_STRIP);
        writeLE16(buffer, TYPE_LONG);
        writeLE32(buffer, 1);
        writeLE32(buffer, height);

        // 279: StripByteCounts
        writeLE16(buffer, TAG_STRIP_BYTE_COUNTS);
        writeLE16(buffer, TYPE_LONG);
        writeLE32(buffer, 1);
        writeLE32(buffer, stripByteCount);

        // 282: XResolution
        writeLE16(buffer, TAG_X_RESOLUTION);
        writeLE16(buffer, TYPE_RATIONAL);
        writeLE32(buffer, 1);
        writeLE32(buffer, xResOffset);

        // 283: YResolution
        writeLE16(buffer, TAG_Y_RESOLUTION);
        writeLE16(buffer, TYPE_RATIONAL);
        writeLE32(buffer, 1);
        writeLE32(buffer, yResOffset);

        // 296: ResolutionUnit
        writeLE16(buffer, TAG_RESOLUTION_UNIT);
        writeLE16(buffer, TYPE_SHORT);
        writeLE32(buffer, 1);
        writeLE32(buffer, RESOLUTION_INCH);

        // Next IFD offset (0 = none)
        writeLE32(buffer, 0);

        // BitsPerSample values (8, 8, 8)
        writeLE16(buffer, 8);
        writeLE16(buffer, 8);
        writeLE16(buffer, 8);

        // XResolution rational (dpi/1)
        writeLE32(buffer, dpi);
        writeLE32(buffer, 1);

        // YResolution rational (dpi/1)
        writeLE32(buffer, dpi);
        writeLE32(buffer, 1);

        // Image data
        buffer.insert(buffer.end(), data, data + stripByteCount);

        // Write to file
        FileHandle outFile{createFile(outputPath)};
        if (!outFile.valid()) {
            return false;
        }

        auto written = outFile.write(buffer.data(), buffer.size());
        return written == static_cast<ssize_t>(buffer.size());
    }

    // Save from JPEG file - reads JPEG dimensions and converts
    template<SizeType PathSize>
    [[nodiscard]] bool saveFromJpeg(
        const StaticString<PathSize>& jpegPath,
        const StaticString<PathSize>& tifPath,
        uint32_t dpi = 100
    ) noexcept {
        // This would require JPEG decoding which is complex
        // For now, return false - use Python PIL for JPEG to TIF conversion
        (void)jpegPath;
        (void)tifPath;
        (void)dpi;
        return false;
    }
};

} // namespace output_module::generators
