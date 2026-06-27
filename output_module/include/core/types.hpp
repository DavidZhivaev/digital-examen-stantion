#pragma once

#include <cstdint>
#include <cstddef>
#include <type_traits>
#include <concepts>

namespace output_module::core {

using BarcodeType = std::int64_t;
using ByteType = std::uint8_t;
using SizeType = std::size_t;

inline constexpr SizeType BARCODE_DIGITS{13};
inline constexpr SizeType UUID_LENGTH{36};
inline constexpr SizeType MAX_PATH_LENGTH{4096};
inline constexpr SizeType MAX_SHEETS{256};
inline constexpr SizeType MAX_ADDITIONAL_LINKS{64};
inline constexpr SizeType CACHE_LINE_SIZE{64};
inline constexpr SizeType PAGE_SIZE{4096};

inline constexpr BarcodeType BARCODE_MIN{1'000'000'000'000LL};
inline constexpr BarcodeType BARCODE_MAX{9'999'999'999'999LL};

template<typename T>
concept Integral = std::is_integral_v<T>;

template<typename T>
concept UnsignedIntegral = std::is_integral_v<T> && std::is_unsigned_v<T>;

template<typename T>
concept Trivial = std::is_trivially_copyable_v<T> && std::is_trivially_destructible_v<T>;

template<typename T>
concept CacheAligned = (alignof(T) >= CACHE_LINE_SIZE);

template<SizeType N>
concept PowerOfTwo = (N > 0) && ((N & (N - 1)) == 0);

template<typename T>
struct RemoveCVRef {
    using Type = std::remove_cv_t<std::remove_reference_t<T>>;
};

template<typename T>
using RemoveCVRefT = typename RemoveCVRef<T>::Type;

enum class SheetType : std::uint8_t {
    Unknown = 0,
    Titul = 1,
    Blan1 = 2,
    Blan2 = 3,
    Additional = 4
};

enum class ResultStatus : std::uint8_t {
    Success = 0,
    ErrorNoSheets = 1,
    ErrorNoBarcode = 2,
    ErrorPdfCreation = 3,
    ErrorZipCreation = 4,
    ErrorFileWrite = 5,
    ErrorInvalidInput = 6
};

template<typename T>
[[nodiscard]] constexpr auto toUnderlying(T value) noexcept -> std::underlying_type_t<T> {
    return static_cast<std::underlying_type_t<T>>(value);
}

} // namespace output_module::core
