#pragma once

#include "types.hpp"
#include "static_string.hpp"
#include "static_vector.hpp"

namespace output_module::core {

struct alignas(CACHE_LINE_SIZE) SheetData {
    PathString imagePath{};
    BarcodeType barcode{0};
    SheetType type{SheetType::Unknown};
    SizeType orderInChain{0};
    bool valid{false};

    constexpr SheetData() noexcept = default;

    constexpr SheetData(
        const char* path,
        BarcodeType bc,
        SheetType t,
        SizeType order = 0
    ) noexcept
        : imagePath{path}
        , barcode{bc}
        , type{t}
        , orderInChain{order}
        , valid{true} {}

    [[nodiscard]] constexpr auto isValid() const noexcept -> bool {
        return valid && barcode >= BARCODE_MIN && barcode <= BARCODE_MAX;
    }
};

using SheetCollection = StaticVector<SheetData, MAX_SHEETS>;

struct alignas(CACHE_LINE_SIZE) WorkChain {
    UuidString workId{};
    BarcodeType titleBarcode{0};
    SheetCollection sheets{};
    bool chainValid{true};

    constexpr WorkChain() noexcept = default;

    [[nodiscard]] constexpr auto sheetCount() const noexcept -> SizeType {
        return sheets.size();
    }

    [[nodiscard]] constexpr auto isValid() const noexcept -> bool {
        return !sheets.empty() && titleBarcode >= BARCODE_MIN && chainValid;
    }

    [[nodiscard]] constexpr auto getBarcodeAt(SizeType index) const noexcept -> BarcodeType {
        if (index < sheets.size()) [[likely]] {
            return sheets[index].barcode;
        }
        return 0;
    }
};

struct alignas(CACHE_LINE_SIZE) PackageResult {
    ResultStatus status{ResultStatus::Success};
    PathString zipPath{};
    PathString pdfFilename{};
    UuidString workId{};
    BarcodeType titleBarcode{0};
    SizeType sheetCount{0};
    bool chainValid{true};

    [[nodiscard]] constexpr auto ok() const noexcept -> bool {
        return status == ResultStatus::Success;
    }

    [[nodiscard]] constexpr auto errorCode() const noexcept -> std::uint8_t {
        return toUnderlying(status);
    }
};

[[nodiscard]] constexpr auto findTitleBarcode(const SheetCollection& sheets) noexcept -> BarcodeType {
    for (const auto& sheet : sheets) {
        if (sheet.type == SheetType::Titul && sheet.isValid()) [[unlikely]] {
            return sheet.barcode;
        }
    }
    if (!sheets.empty() && sheets[0].isValid()) {
        return sheets[0].barcode;
    }
    return 0;
}

} // namespace output_module::core
