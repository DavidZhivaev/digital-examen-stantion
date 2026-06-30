#pragma once

#include "zip_primitives.hpp"
#include "../core/types.hpp"
#include "../core/static_string.hpp"
#include "../core/static_vector.hpp"
#include "../core/file_handle.hpp"
#include <array>
#include <vector>

namespace output_module::generators {

using namespace core;
using namespace zip;

inline constexpr SizeType ZIP_BUFFER_SIZE{1ULL << 21};  // 2MB
inline constexpr SizeType MAX_ZIP_ENTRIES{16};
inline constexpr SizeType MAX_FILE_READ_SIZE{1ULL << 21};  // 2MB

struct ZipEntryInfo {
    StaticString<256> fileName{};
    std::uint32_t localHeaderOffset{0};
    std::uint32_t crc32{0};
    std::uint32_t compressedSize{0};
    std::uint32_t uncompressedSize{0};
};

template<SizeType MaxEntries = MAX_ZIP_ENTRIES>
class alignas(CACHE_LINE_SIZE) ZipPackager {
private:
    LinearBuffer<ZIP_BUFFER_SIZE> outputBuffer_{};
    StaticVector<ZipEntryInfo, MaxEntries> entries_{};

public:
    constexpr ZipPackager() noexcept = default;

    auto reset() noexcept -> void {
        outputBuffer_.clear();
        entries_.clear();
    }

    auto addFileFromMemory(
        const char* fileName,
        const ByteType* data,
        SizeType dataSize
    ) noexcept -> bool {
        if (entries_.full()) [[unlikely]] {
            return false;
        }

        SizeType fileNameLen{0};
        while (fileName[fileNameLen] != '\0') {
            ++fileNameLen;
        }

        ZipEntryInfo entry{};
        entry.fileName = StaticString<256>{fileName};
        entry.localHeaderOffset = static_cast<std::uint32_t>(outputBuffer_.size());
        entry.crc32 = calculateCrc32(data, dataSize);
        entry.compressedSize = static_cast<std::uint32_t>(dataSize);
        entry.uncompressedSize = static_cast<std::uint32_t>(dataSize);

        writeLocalFileHeader(
            outputBuffer_,
            fileName,
            fileNameLen,
            entry.crc32,
            entry.compressedSize,
            entry.uncompressedSize
        );

        outputBuffer_.append(data, dataSize);

        entries_.pushBack(entry);
        return true;
    }

    template<SizeType PathSize>
    auto addFileFromDisk(
        const char* fileNameInZip,
        const StaticString<PathSize>& filePath
    ) noexcept -> bool {
        if (entries_.full()) [[unlikely]] {
            return false;
        }

        FileHandle file{openFileRead(filePath)};
        if (!file.valid()) [[unlikely]] {
            return false;
        }

        auto fileSize{static_cast<SizeType>(file.size())};
        if (fileSize > MAX_FILE_READ_SIZE) [[unlikely]] {
            return false;
        }

        std::vector<ByteType> fileBuffer(fileSize);
        auto bytesRead{file.read(fileBuffer.data(), fileSize)};
        if (bytesRead <= 0) [[unlikely]] {
            return false;
        }

        return addFileFromMemory(
            fileNameInZip,
            fileBuffer.data(),
            static_cast<SizeType>(bytesRead)
        );
    }

    template<SizeType PathSize>
    [[nodiscard]] auto finalize(
        const StaticString<PathSize>& outputPath
    ) noexcept -> bool {
        if (entries_.empty()) [[unlikely]] {
            return false;
        }

        std::uint32_t centralDirOffset{static_cast<std::uint32_t>(outputBuffer_.size())};

        for (const auto& entry : entries_) {
            SizeType fileNameLen{entry.fileName.size()};

            writeCentralDirHeader(
                outputBuffer_,
                entry.fileName.cStr(),
                fileNameLen,
                entry.crc32,
                entry.compressedSize,
                entry.uncompressedSize,
                entry.localHeaderOffset
            );
        }

        std::uint32_t centralDirSize{
            static_cast<std::uint32_t>(outputBuffer_.size()) - centralDirOffset
        };

        writeEndCentralDir(
            outputBuffer_,
            static_cast<std::uint16_t>(entries_.size()),
            centralDirSize,
            centralDirOffset
        );

        FileHandle outFile{createFile(outputPath)};
        if (!outFile.valid()) [[unlikely]] {
            return false;
        }

        auto written{outFile.write(outputBuffer_.data(), outputBuffer_.size())};
        return written == static_cast<ssize_t>(outputBuffer_.size());
    }

    [[nodiscard]] constexpr auto entryCount() const noexcept -> SizeType {
        return entries_.size();
    }
};

} // namespace output_module::generators
