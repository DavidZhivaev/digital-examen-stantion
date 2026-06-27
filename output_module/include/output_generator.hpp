#pragma once

#include "core/types.hpp"
#include "core/static_string.hpp"
#include "core/static_vector.hpp"
#include "core/file_handle.hpp"
#include "core/sheet_data.hpp"
#include "formatters/json_builder.hpp"
#include "generators/pdf_generator.hpp"
#include "generators/zip_packager.hpp"

namespace output_module {

using namespace core;
using namespace formatters;
using namespace generators;

template<typename Derived>
class OutputGeneratorBase {
protected:
    PathString outputDir_{};

    [[nodiscard]] auto derived() noexcept -> Derived& {
        return static_cast<Derived&>(*this);
    }

    [[nodiscard]] auto derived() const noexcept -> const Derived& {
        return static_cast<const Derived&>(*this);
    }

public:
    constexpr OutputGeneratorBase() noexcept = default;

    explicit OutputGeneratorBase(const char* outputDir) noexcept
        : outputDir_{outputDir} {}

    template<SizeType N>
    explicit OutputGeneratorBase(const StaticString<N>& outputDir) noexcept {
        outputDir_.append(outputDir);
    }

    auto setOutputDir(const char* dir) noexcept -> void {
        outputDir_.clear();
        outputDir_.append(dir);
    }

    [[nodiscard]] auto createPackage(WorkChain& chain) noexcept -> PackageResult {
        return derived().createPackageImpl(chain);
    }
};

class alignas(CACHE_LINE_SIZE) OutputGenerator
    : public OutputGeneratorBase<OutputGenerator> {
private:
    PdfGenerator<MAX_SHEETS> pdfGenerator_{};
    ZipPackager<16> zipPackager_{};

    friend class OutputGeneratorBase<OutputGenerator>;

    [[nodiscard]] auto buildPdfPath(BarcodeType barcode) const noexcept -> PathString {
        PathString path{};
        path.append(outputDir_);
        path.append('/');
        auto barcodeStr{formatBarcode(barcode)};
        path.append(barcodeStr);
        path.append(".pdf");
        return path;
    }

    [[nodiscard]] auto buildZipPath(const UuidString& workId) const noexcept -> PathString {
        PathString path{};
        path.append(outputDir_);
        path.append('/');
        path.append(workId);
        path.append(".zip");
        return path;
    }

    [[nodiscard]] auto buildPdfFilename(BarcodeType barcode) const noexcept -> StaticString<32> {
        StaticString<32> filename{};
        auto barcodeStr{formatBarcode(barcode)};
        filename.append(barcodeStr);
        filename.append(".pdf");
        return filename;
    }

    [[nodiscard]] auto createPackageImpl(WorkChain& chain) noexcept -> PackageResult {
        PackageResult result{};

        if (chain.sheets.empty()) [[unlikely]] {
            result.status = ResultStatus::ErrorNoSheets;
            return result;
        }

        BarcodeType titleBarcode{chain.titleBarcode};
        if (titleBarcode == 0) {
            titleBarcode = findTitleBarcode(chain.sheets);
            chain.titleBarcode = titleBarcode;
        }

        if (titleBarcode == 0) [[unlikely]] {
            result.status = ResultStatus::ErrorNoBarcode;
            return result;
        }

        if (chain.workId.empty()) [[unlikely]] {
            result.status = ResultStatus::ErrorInvalidInput;
            return result;
        }

        createDirectory(outputDir_);

        auto pdfPath{buildPdfPath(titleBarcode)};
        auto pdfFilename{buildPdfFilename(titleBarcode)};

        pdfGenerator_.reset();
        if (!pdfGenerator_.generate(chain.sheets, pdfPath)) [[unlikely]] {
            result.status = ResultStatus::ErrorPdfCreation;
            return result;
        }

        auto jsonBuilder{buildResultsJson(chain)};

        zipPackager_.reset();

        if (!zipPackager_.addFileFromDisk(pdfFilename.cStr(), pdfPath)) [[unlikely]] {
            result.status = ResultStatus::ErrorZipCreation;
            return result;
        }

        if (!zipPackager_.addFileFromMemory(
                "results.json",
                jsonBuilder.data(),
                jsonBuilder.size())) [[unlikely]] {
            result.status = ResultStatus::ErrorZipCreation;
            return result;
        }

        auto zipPath{buildZipPath(chain.workId)};

        if (!zipPackager_.finalize(zipPath)) [[unlikely]] {
            result.status = ResultStatus::ErrorZipCreation;
            return result;
        }

        result.status = ResultStatus::Success;
        result.zipPath = zipPath;
        result.pdfFilename.append(pdfFilename);
        result.workId = chain.workId;
        result.titleBarcode = titleBarcode;
        result.sheetCount = chain.sheetCount();
        result.chainValid = chain.chainValid;

        return result;
    }

public:
    using OutputGeneratorBase::OutputGeneratorBase;
};

template<SizeType MaxWorks = 64>
class alignas(CACHE_LINE_SIZE) BatchOutputGenerator {
private:
    OutputGenerator generator_{};
    StaticVector<PackageResult, MaxWorks> results_{};

public:
    constexpr BatchOutputGenerator() noexcept = default;

    explicit BatchOutputGenerator(const char* outputDir) noexcept
        : generator_{outputDir} {}

    auto setOutputDir(const char* dir) noexcept -> void {
        generator_.setOutputDir(dir);
    }

    template<typename ChainContainer>
    auto processAll(ChainContainer& chains) noexcept -> const StaticVector<PackageResult, MaxWorks>& {
        results_.clear();

        for (auto& chain : chains) {
            auto result{generator_.createPackage(chain)};
            results_.pushBack(result);
        }

        return results_;
    }

    [[nodiscard]] auto results() const noexcept -> const StaticVector<PackageResult, MaxWorks>& {
        return results_;
    }

    [[nodiscard]] constexpr auto successCount() const noexcept -> SizeType {
        SizeType count{0};
        for (const auto& result : results_) {
            if (result.ok()) {
                ++count;
            }
        }
        return count;
    }

    [[nodiscard]] constexpr auto failureCount() const noexcept -> SizeType {
        return results_.size() - successCount();
    }
};

} // namespace output_module
