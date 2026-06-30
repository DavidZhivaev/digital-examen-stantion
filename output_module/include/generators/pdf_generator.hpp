#pragma once

#include "pdf_primitives.hpp"
#include "../core/types.hpp"
#include "../core/static_string.hpp"
#include "../core/static_vector.hpp"
#include "../core/file_handle.hpp"
#include "../core/sheet_data.hpp"
#include <array>
#include <vector>
#include <cstring>

namespace output_module::generators {

using namespace core;
using namespace pdf;

inline constexpr SizeType IMAGE_READ_BUFFER_SIZE{4ULL << 20};  // 4MB for images
inline constexpr SizeType PDF_WRITE_BUFFER_SIZE{1ULL << 21};   // 2MB for PDF output

template<SizeType MaxPages = MAX_SHEETS>
class alignas(CACHE_LINE_SIZE) PdfGenerator {
private:
    LinearBuffer<PDF_WRITE_BUFFER_SIZE> outputBuffer_{};
    PdfXrefTable<MaxPages * 2 + 16> xref_{};
    int nextObjectNum_{1};

    constexpr auto startObject(int objNum) noexcept -> void {
        xref_.addEntry(outputBuffer_.size());
        writeInt(outputBuffer_, objNum);
        writeBytes(outputBuffer_, " 0 obj\n");
    }

    constexpr auto endObject() noexcept -> void {
        writeLine(outputBuffer_, "endobj");
    }

    constexpr auto writeHeader() noexcept -> void {
        writeLine(outputBuffer_, "%PDF-1.4");
        outputBuffer_.append('%');
        outputBuffer_.append(0xE2);
        outputBuffer_.append(0xE3);
        outputBuffer_.append(0xCF);
        outputBuffer_.append(0xD3);
        outputBuffer_.append('\n');
    }

    constexpr auto writeCatalog(int pagesRef) noexcept -> int {
        int objNum{nextObjectNum_++};
        startObject(objNum);
        writeBytes(outputBuffer_, "<< /Type /Catalog /Pages ");
        writeInt(outputBuffer_, pagesRef);
        writeLine(outputBuffer_, " 0 R >>");
        endObject();
        return objNum;
    }

    auto writePages(
        const StaticVector<int, MaxPages>& pageRefs,
        int mediaBoxWidth,
        int mediaBoxHeight
    ) noexcept -> int {
        int objNum{nextObjectNum_++};
        startObject(objNum);
        writeBytes(outputBuffer_, "<< /Type /Pages /Kids [");

        for (SizeType i{0}; i < pageRefs.size(); ++i) {
            if (i > 0) {
                outputBuffer_.append(' ');
            }
            writeInt(outputBuffer_, pageRefs[i]);
            writeBytes(outputBuffer_, " 0 R");
        }

        writeBytes(outputBuffer_, "] /Count ");
        writeInt(outputBuffer_, static_cast<int>(pageRefs.size()));
        writeBytes(outputBuffer_, " /MediaBox [0 0 ");
        writeInt(outputBuffer_, mediaBoxWidth);
        outputBuffer_.append(' ');
        writeInt(outputBuffer_, mediaBoxHeight);
        writeLine(outputBuffer_, "] >>");
        endObject();
        return objNum;
    }

    auto writePage(
        int parentRef,
        int contentsRef,
        int resourcesRef
    ) noexcept -> int {
        int objNum{nextObjectNum_++};
        startObject(objNum);
        writeBytes(outputBuffer_, "<< /Type /Page /Parent ");
        writeInt(outputBuffer_, parentRef);
        writeBytes(outputBuffer_, " 0 R /Contents ");
        writeInt(outputBuffer_, contentsRef);
        writeBytes(outputBuffer_, " 0 R /Resources ");
        writeInt(outputBuffer_, resourcesRef);
        writeLine(outputBuffer_, " 0 R >>");
        endObject();
        return objNum;
    }

    auto writeImageXObject(
        const ByteType* imageData,
        SizeType imageSize,
        const ImageDimensions& dims
    ) noexcept -> int {
        int objNum{nextObjectNum_++};
        startObject(objNum);

        writeBytes(outputBuffer_, "<< /Type /XObject /Subtype /Image /Width ");
        writeInt(outputBuffer_, dims.width);
        writeBytes(outputBuffer_, " /Height ");
        writeInt(outputBuffer_, dims.height);

        if (dims.components == 1) {
            writeBytes(outputBuffer_, " /ColorSpace /DeviceGray");
        } else if (dims.components == 4) {
            writeBytes(outputBuffer_, " /ColorSpace /DeviceCMYK");
        } else {
            writeBytes(outputBuffer_, " /ColorSpace /DeviceRGB");
        }

        writeBytes(outputBuffer_, " /BitsPerComponent ");
        writeInt(outputBuffer_, dims.bitsPerComponent);
        writeBytes(outputBuffer_, " /Filter /DCTDecode /Length ");
        writeInt(outputBuffer_, static_cast<int>(imageSize));
        writeLine(outputBuffer_, " >>");
        writeLine(outputBuffer_, "stream");

        outputBuffer_.append(imageData, imageSize);
        outputBuffer_.append('\n');

        writeLine(outputBuffer_, "endstream");
        endObject();
        return objNum;
    }

    auto writePageContents(
        int imageWidth,
        int imageHeight,
        int pageWidth,
        int pageHeight
    ) noexcept -> int {
        LinearBuffer<512> streamContent{};

        writeBytes(streamContent, "q ");

        float scaleX{static_cast<float>(pageWidth) / static_cast<float>(imageWidth)};
        float scaleY{static_cast<float>(pageHeight) / static_cast<float>(imageHeight)};
        float scale{scaleX < scaleY ? scaleX : scaleY};

        float scaledWidth{static_cast<float>(imageWidth) * scale};
        float scaledHeight{static_cast<float>(imageHeight) * scale};

        float offsetX{(static_cast<float>(pageWidth) - scaledWidth) / 2.0f};
        float offsetY{(static_cast<float>(pageHeight) - scaledHeight) / 2.0f};

        writeFloat(streamContent, scaledWidth);
        writeBytes(streamContent, " 0 0 ");
        writeFloat(streamContent, scaledHeight);
        outputBuffer_.append(' ');
        writeFloat(streamContent, offsetX);
        outputBuffer_.append(' ');
        writeFloat(streamContent, offsetY);
        writeBytes(streamContent, " cm /Im0 Do Q");

        int objNum{nextObjectNum_++};
        startObject(objNum);
        writeBytes(outputBuffer_, "<< /Length ");
        writeInt(outputBuffer_, static_cast<int>(streamContent.size()));
        writeLine(outputBuffer_, " >>");
        writeLine(outputBuffer_, "stream");
        outputBuffer_.append(streamContent.data(), streamContent.size());
        outputBuffer_.append('\n');
        writeLine(outputBuffer_, "endstream");
        endObject();
        return objNum;
    }

    auto writeResources(int imageRef) noexcept -> int {
        int objNum{nextObjectNum_++};
        startObject(objNum);
        writeBytes(outputBuffer_, "<< /XObject << /Im0 ");
        writeInt(outputBuffer_, imageRef);
        writeLine(outputBuffer_, " 0 R >> >>");
        endObject();
        return objNum;
    }

    auto writeTrailer(int rootRef, SizeType xrefOffset) noexcept -> void {
        writeLine(outputBuffer_, "trailer");
        writeBytes(outputBuffer_, "<< /Size ");
        writeInt(outputBuffer_, nextObjectNum_);
        writeBytes(outputBuffer_, " /Root ");
        writeInt(outputBuffer_, rootRef);
        writeLine(outputBuffer_, " 0 R >>");
        writeBytes(outputBuffer_, "startxref\n");
        writeInt(outputBuffer_, static_cast<int>(xrefOffset));
        outputBuffer_.append('\n');
        writeLine(outputBuffer_, "%%EOF");
    }

public:
    constexpr PdfGenerator() noexcept = default;

    auto reset() noexcept -> void {
        outputBuffer_.clear();
        xref_ = PdfXrefTable<MaxPages * 2 + 16>{};
        nextObjectNum_ = 1;
    }

    template<SizeType PathSize>
    [[nodiscard]] auto generate(
        const SheetCollection& sheets,
        const StaticString<PathSize>& outputPath
    ) noexcept -> bool {
        reset();

        if (sheets.empty()) [[unlikely]] {
            return false;
        }

        writeHeader();

        xref_.addEntry(0);

        StaticVector<int, MaxPages> pageRefs{};
        std::vector<ByteType> imageBuffer(IMAGE_READ_BUFFER_SIZE);

        int pagesObjNum{nextObjectNum_++};

        for (const auto& sheet : sheets) {
            if (sheet.imagePath.empty()) [[unlikely]] {
                continue;
            }

            FileHandle imageFile{openFileRead(sheet.imagePath)};
            if (!imageFile.valid()) [[unlikely]] {
                continue;
            }

            auto imageSize{static_cast<SizeType>(imageFile.size())};
            if (imageSize > IMAGE_READ_BUFFER_SIZE) [[unlikely]] {
                continue;
            }

            auto bytesRead{imageFile.read(imageBuffer.data(), imageSize)};
            if (bytesRead <= 0) [[unlikely]] {
                continue;
            }

            auto actualSize{static_cast<SizeType>(bytesRead)};
            auto dims{parseJpegDimensions(imageBuffer.data(), actualSize)};

            if (dims.width == 0 || dims.height == 0) [[unlikely]] {
                continue;
            }

            int imageRef{writeImageXObject(imageBuffer.data(), actualSize, dims)};

            int contentsRef{writePageContents(
                dims.width,
                dims.height,
                static_cast<int>(A4_WIDTH_PT),
                static_cast<int>(A4_HEIGHT_PT)
            )};

            int resourcesRef{writeResources(imageRef)};

            int pageRef{writePage(pagesObjNum, contentsRef, resourcesRef)};
            pageRefs.pushBack(pageRef);
        }

        if (pageRefs.empty()) [[unlikely]] {
            return false;
        }

        SizeType pagesOffset{outputBuffer_.size()};
        xref_.addEntry(pagesOffset);

        startObject(pagesObjNum);
        writeBytes(outputBuffer_, "<< /Type /Pages /Kids [");

        for (SizeType i{0}; i < pageRefs.size(); ++i) {
            if (i > 0) {
                outputBuffer_.append(' ');
            }
            writeInt(outputBuffer_, pageRefs[i]);
            writeBytes(outputBuffer_, " 0 R");
        }

        writeBytes(outputBuffer_, "] /Count ");
        writeInt(outputBuffer_, static_cast<int>(pageRefs.size()));
        writeBytes(outputBuffer_, " /MediaBox [0 0 ");
        writeInt(outputBuffer_, static_cast<int>(A4_WIDTH_PT));
        outputBuffer_.append(' ');
        writeInt(outputBuffer_, static_cast<int>(A4_HEIGHT_PT));
        writeLine(outputBuffer_, "] >>");
        endObject();

        int catalogRef{writeCatalog(pagesObjNum)};

        SizeType xrefOffset{outputBuffer_.size()};
        xref_.writeXref(outputBuffer_);

        writeTrailer(catalogRef, xrefOffset);

        FileHandle outFile{createFile(outputPath)};
        if (!outFile.valid()) [[unlikely]] {
            return false;
        }

        auto written{outFile.write(outputBuffer_.data(), outputBuffer_.size())};
        return written == static_cast<ssize_t>(outputBuffer_.size());
    }
};

} // namespace output_module::generators
