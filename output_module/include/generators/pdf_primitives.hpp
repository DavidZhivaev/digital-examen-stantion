#pragma once

#include "../core/types.hpp"
#include "../core/static_string.hpp"
#include "../core/memory_buffer.hpp"
#include <array>

namespace output_module::generators::pdf {

using namespace core;

inline constexpr float A4_WIDTH_PT{595.27f};
inline constexpr float A4_HEIGHT_PT{841.89f};
inline constexpr SizeType PDF_HEADER_SIZE{64};
inline constexpr SizeType PDF_BUFFER_SIZE{1ULL << 20};

template<SizeType N>
auto writeBytes(LinearBuffer<N>& buf, const char* str) noexcept -> SizeType {
    SizeType written{0};
    while (str[written] != '\0') {
        buf.append(static_cast<ByteType>(str[written]));
        ++written;
    }
    return written;
}

template<SizeType N>
auto writeInt(LinearBuffer<N>& buf, int value) noexcept -> SizeType {
    auto str{intToString(value)};
    return buf.append(str.data(), str.size());
}

template<SizeType N>
auto writeFloat(LinearBuffer<N>& buf, float value, int precision = 2) noexcept -> SizeType {
    int intPart{static_cast<int>(value)};
    float fracPart{value - static_cast<float>(intPart)};
    if (fracPart < 0) {
        fracPart = -fracPart;
    }

    SizeType written{0};

    if (value < 0 && intPart == 0) {
        buf.append('-');
        ++written;
    }

    auto intStr{intToString(intPart)};
    written += buf.append(intStr.data(), intStr.size());

    buf.append('.');
    ++written;

    for (int i{0}; i < precision; ++i) {
        fracPart *= 10.0f;
    }

    int fracInt{static_cast<int>(fracPart + 0.5f)};
    auto fracStr{intToStringPadded<2>(fracInt)};
    written += buf.append(fracStr.data(), fracStr.size());

    return written;
}

template<SizeType N>
auto writeLine(LinearBuffer<N>& buf, const char* str) noexcept -> SizeType {
    SizeType written{writeBytes(buf, str)};
    buf.append('\n');
    return written + 1;
}

struct PdfObjectRef {
    int objectNumber{0};
    int generation{0};

    constexpr PdfObjectRef() noexcept = default;
    constexpr explicit PdfObjectRef(int objNum) noexcept : objectNumber{objNum}, generation{0} {}
};

template<SizeType MaxObjects = 128>
class alignas(CACHE_LINE_SIZE) PdfXrefTable {
private:
    std::array<SizeType, MaxObjects> offsets_{};
    SizeType count_{0};

public:
    constexpr PdfXrefTable() noexcept = default;

    constexpr auto addEntry(SizeType offset) noexcept -> int {
        if (count_ < MaxObjects) [[likely]] {
            offsets_[count_] = offset;
            return static_cast<int>(count_++);
        }
        return -1;
    }

    [[nodiscard]] constexpr auto count() const noexcept -> SizeType {
        return count_;
    }

    [[nodiscard]] constexpr auto getOffset(SizeType index) const noexcept -> SizeType {
        return index < count_ ? offsets_[index] : 0;
    }

    template<SizeType N>
    auto writeXref(LinearBuffer<N>& buf) const noexcept -> SizeType {
        SizeType written{0};

        written += writeLine(buf, "xref");

        written += writeBytes(buf, "0 ");
        written += writeInt(buf, static_cast<int>(count_));
        buf.append('\n');
        ++written;

        for (SizeType i{0}; i < count_; ++i) {
            auto offsetStr{intToStringPadded<10>(static_cast<int>(offsets_[i]))};
            written += buf.append(offsetStr.data(), offsetStr.size());
            buf.append(' ');
            ++written;

            written += writeBytes(buf, "00000");
            buf.append(' ');
            ++written;

            if (i == 0) {
                buf.append('f');
            } else {
                buf.append('n');
            }
            ++written;

            buf.append('\r');
            buf.append('\n');
            written += 2;
        }

        return written;
    }
};

struct ImageDimensions {
    int width{0};
    int height{0};
    int components{3};
    int bitsPerComponent{8};
};

[[nodiscard]] constexpr auto parseJpegDimensions(
    const ByteType* data,
    SizeType size
) noexcept -> ImageDimensions {
    ImageDimensions dims{};

    if (size < 4) [[unlikely]] {
        return dims;
    }

    if (data[0] != 0xFF || data[1] != 0xD8) [[unlikely]] {
        return dims;
    }

    SizeType pos{2};

    while (pos + 4 < size) {
        if (data[pos] != 0xFF) [[unlikely]] {
            ++pos;
            continue;
        }

        ByteType marker{data[pos + 1]};

        if (marker == 0xC0 || marker == 0xC1 || marker == 0xC2) [[unlikely]] {
            if (pos + 9 < size) {
                dims.bitsPerComponent = data[pos + 4];
                dims.height = (static_cast<int>(data[pos + 5]) << 8) | data[pos + 6];
                dims.width = (static_cast<int>(data[pos + 7]) << 8) | data[pos + 8];
                dims.components = data[pos + 9];
                return dims;
            }
        }

        if (marker == 0xD9 || marker == 0xDA) [[unlikely]] {
            break;
        }

        if (marker >= 0xD0 && marker <= 0xD8) [[unlikely]] {
            pos += 2;
            continue;
        }

        if (pos + 3 < size) {
            SizeType segmentLength{
                (static_cast<SizeType>(data[pos + 2]) << 8) | data[pos + 3]
            };
            pos += 2 + segmentLength;
        } else {
            break;
        }
    }

    return dims;
}

} // namespace output_module::generators::pdf
