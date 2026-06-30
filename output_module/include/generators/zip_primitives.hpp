#pragma once

#include "../core/types.hpp"
#include "../core/static_string.hpp"
#include "../core/memory_buffer.hpp"
#include <array>

namespace output_module::generators::zip {

using namespace core;

inline constexpr std::uint32_t LOCAL_FILE_HEADER_SIG{0x04034B50};
inline constexpr std::uint32_t CENTRAL_DIR_HEADER_SIG{0x02014B50};
inline constexpr std::uint32_t END_CENTRAL_DIR_SIG{0x06054B50};
inline constexpr std::uint16_t VERSION_NEEDED{20};
inline constexpr std::uint16_t VERSION_MADE_BY{0x031E};
inline constexpr std::uint16_t COMPRESSION_STORED{0};
inline constexpr std::uint16_t COMPRESSION_DEFLATE{8};

struct alignas(4) LocalFileHeader {
    std::uint32_t signature{LOCAL_FILE_HEADER_SIG};
    std::uint16_t versionNeeded{VERSION_NEEDED};
    std::uint16_t flags{0};
    std::uint16_t compression{COMPRESSION_STORED};
    std::uint16_t modTime{0};
    std::uint16_t modDate{0};
    std::uint32_t crc32{0};
    std::uint32_t compressedSize{0};
    std::uint32_t uncompressedSize{0};
    std::uint16_t fileNameLength{0};
    std::uint16_t extraFieldLength{0};
};

struct alignas(4) CentralDirHeader {
    std::uint32_t signature{CENTRAL_DIR_HEADER_SIG};
    std::uint16_t versionMadeBy{VERSION_MADE_BY};
    std::uint16_t versionNeeded{VERSION_NEEDED};
    std::uint16_t flags{0};
    std::uint16_t compression{COMPRESSION_STORED};
    std::uint16_t modTime{0};
    std::uint16_t modDate{0};
    std::uint32_t crc32{0};
    std::uint32_t compressedSize{0};
    std::uint32_t uncompressedSize{0};
    std::uint16_t fileNameLength{0};
    std::uint16_t extraFieldLength{0};
    std::uint16_t commentLength{0};
    std::uint16_t diskStart{0};
    std::uint16_t internalAttribs{0};
    std::uint32_t externalAttribs{0};
    std::uint32_t localHeaderOffset{0};
};

struct alignas(4) EndCentralDirRecord {
    std::uint32_t signature{END_CENTRAL_DIR_SIG};
    std::uint16_t diskNumber{0};
    std::uint16_t centralDirDisk{0};
    std::uint16_t entriesOnDisk{0};
    std::uint16_t totalEntries{0};
    std::uint32_t centralDirSize{0};
    std::uint32_t centralDirOffset{0};
    std::uint16_t commentLength{0};
};

inline constexpr std::array<std::uint32_t, 256> CRC32_TABLE = [] {
    std::array<std::uint32_t, 256> table{};
    for (std::uint32_t i{0}; i < 256; ++i) {
        std::uint32_t crc{i};
        for (int j{0}; j < 8; ++j) {
            if (crc & 1) {
                crc = (crc >> 1) ^ 0xEDB88320;
            } else {
                crc >>= 1;
            }
        }
        table[i] = crc;
    }
    return table;
}();

[[nodiscard]] constexpr auto calculateCrc32(
    const ByteType* data,
    SizeType size
) noexcept -> std::uint32_t {
    std::uint32_t crc{0xFFFFFFFF};
    for (SizeType i{0}; i < size; ++i) {
        crc = CRC32_TABLE[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    }
    return crc ^ 0xFFFFFFFF;
}

template<SizeType N>
auto writeLE16(LinearBuffer<N>& buf, std::uint16_t value) noexcept -> void {
    buf.append(static_cast<ByteType>(value & 0xFF));
    buf.append(static_cast<ByteType>((value >> 8) & 0xFF));
}

template<SizeType N>
auto writeLE32(LinearBuffer<N>& buf, std::uint32_t value) noexcept -> void {
    buf.append(static_cast<ByteType>(value & 0xFF));
    buf.append(static_cast<ByteType>((value >> 8) & 0xFF));
    buf.append(static_cast<ByteType>((value >> 16) & 0xFF));
    buf.append(static_cast<ByteType>((value >> 24) & 0xFF));
}

template<SizeType BufferSize>
auto writeLocalFileHeader(
    LinearBuffer<BufferSize>& buf,
    const char* fileName,
    SizeType fileNameLen,
    std::uint32_t crc,
    std::uint32_t compressedSize,
    std::uint32_t uncompressedSize
) noexcept -> SizeType {
    SizeType startPos{buf.size()};

    writeLE32(buf, LOCAL_FILE_HEADER_SIG);
    writeLE16(buf, VERSION_NEEDED);
    writeLE16(buf, 0);
    writeLE16(buf, COMPRESSION_STORED);
    writeLE16(buf, 0);
    writeLE16(buf, 0x5421);
    writeLE32(buf, crc);
    writeLE32(buf, compressedSize);
    writeLE32(buf, uncompressedSize);
    writeLE16(buf, static_cast<std::uint16_t>(fileNameLen));
    writeLE16(buf, 0);

    buf.append(fileName, fileNameLen);

    return buf.size() - startPos;
}

template<SizeType BufferSize>
auto writeCentralDirHeader(
    LinearBuffer<BufferSize>& buf,
    const char* fileName,
    SizeType fileNameLen,
    std::uint32_t crc,
    std::uint32_t compressedSize,
    std::uint32_t uncompressedSize,
    std::uint32_t localHeaderOffset
) noexcept -> SizeType {
    SizeType startPos{buf.size()};

    writeLE32(buf, CENTRAL_DIR_HEADER_SIG);
    writeLE16(buf, VERSION_MADE_BY);
    writeLE16(buf, VERSION_NEEDED);
    writeLE16(buf, 0);
    writeLE16(buf, COMPRESSION_STORED);
    writeLE16(buf, 0);
    writeLE16(buf, 0x5421);
    writeLE32(buf, crc);
    writeLE32(buf, compressedSize);
    writeLE32(buf, uncompressedSize);
    writeLE16(buf, static_cast<std::uint16_t>(fileNameLen));
    writeLE16(buf, 0);
    writeLE16(buf, 0);
    writeLE16(buf, 0);
    writeLE16(buf, 0);
    writeLE32(buf, 0x81A40000);
    writeLE32(buf, localHeaderOffset);

    buf.append(fileName, fileNameLen);

    return buf.size() - startPos;
}

template<SizeType BufferSize>
auto writeEndCentralDir(
    LinearBuffer<BufferSize>& buf,
    std::uint16_t entryCount,
    std::uint32_t centralDirSize,
    std::uint32_t centralDirOffset
) noexcept -> SizeType {
    SizeType startPos{buf.size()};

    writeLE32(buf, END_CENTRAL_DIR_SIG);
    writeLE16(buf, 0);
    writeLE16(buf, 0);
    writeLE16(buf, entryCount);
    writeLE16(buf, entryCount);
    writeLE32(buf, centralDirSize);
    writeLE32(buf, centralDirOffset);
    writeLE16(buf, 0);

    return buf.size() - startPos;
}

} // namespace output_module::generators::zip
