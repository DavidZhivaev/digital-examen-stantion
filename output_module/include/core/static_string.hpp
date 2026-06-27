#pragma once

#include "types.hpp"
#include <array>
#include <cstring>
#include <algorithm>

namespace output_module::core {

template<SizeType Capacity>
    requires (Capacity > 0)
class alignas(CACHE_LINE_SIZE) StaticString {
public:
    using ValueType = char;
    using SizeType = core::SizeType;
    using Iterator = ValueType*;
    using ConstIterator = const ValueType*;

private:
    std::array<ValueType, Capacity> data_{};
    SizeType length_{0};

public:
    constexpr StaticString() noexcept = default;

    constexpr explicit StaticString(const char* str) noexcept {
        if (str != nullptr) [[likely]] {
            while (length_ < Capacity - 1 && str[length_] != '\0') {
                data_[length_] = str[length_];
                ++length_;
            }
        }
        data_[length_] = '\0';
    }

    template<SizeType N>
        requires (N <= Capacity)
    constexpr explicit StaticString(const std::array<char, N>& arr) noexcept {
        for (SizeType i{0}; i < N && arr[i] != '\0'; ++i) {
            data_[i] = arr[i];
            ++length_;
        }
        data_[length_] = '\0';
    }

    [[nodiscard]] constexpr auto size() const noexcept -> SizeType {
        return length_;
    }

    [[nodiscard]] constexpr auto capacity() const noexcept -> SizeType {
        return Capacity;
    }

    [[nodiscard]] constexpr auto empty() const noexcept -> bool {
        return length_ == 0;
    }

    [[nodiscard]] constexpr auto data() noexcept -> ValueType* {
        return data_.data();
    }

    [[nodiscard]] constexpr auto data() const noexcept -> const ValueType* {
        return data_.data();
    }

    [[nodiscard]] constexpr auto cStr() const noexcept -> const char* {
        return data_.data();
    }

    [[nodiscard]] constexpr auto operator[](SizeType index) noexcept -> ValueType& {
        return data_[index];
    }

    [[nodiscard]] constexpr auto operator[](SizeType index) const noexcept -> const ValueType& {
        return data_[index];
    }

    constexpr auto clear() noexcept -> void {
        length_ = 0;
        data_[0] = '\0';
    }

    constexpr auto append(char c) noexcept -> bool {
        if (length_ < Capacity - 1) [[likely]] {
            data_[length_++] = c;
            data_[length_] = '\0';
            return true;
        }
        return false;
    }

    constexpr auto append(const char* str) noexcept -> bool {
        if (str == nullptr) [[unlikely]] {
            return false;
        }
        SizeType i{0};
        while (str[i] != '\0' && length_ < Capacity - 1) {
            data_[length_++] = str[i++];
        }
        data_[length_] = '\0';
        return str[i] == '\0';
    }

    template<SizeType OtherCap>
    constexpr auto append(const StaticString<OtherCap>& other) noexcept -> bool {
        for (SizeType i{0}; i < other.size() && length_ < Capacity - 1; ++i) {
            data_[length_++] = other[i];
        }
        data_[length_] = '\0';
        return true;
    }

    [[nodiscard]] constexpr auto begin() noexcept -> Iterator {
        return data_.data();
    }

    [[nodiscard]] constexpr auto end() noexcept -> Iterator {
        return data_.data() + length_;
    }

    [[nodiscard]] constexpr auto begin() const noexcept -> ConstIterator {
        return data_.data();
    }

    [[nodiscard]] constexpr auto end() const noexcept -> ConstIterator {
        return data_.data() + length_;
    }
};

using PathString = StaticString<MAX_PATH_LENGTH>;
using BarcodeString = StaticString<BARCODE_DIGITS + 1>;
using UuidString = StaticString<UUID_LENGTH + 1>;

template<Integral T, SizeType BufferSize = 32>
[[nodiscard]] constexpr auto intToString(T value) noexcept -> StaticString<BufferSize> {
    StaticString<BufferSize> result{};
    std::array<char, BufferSize> buffer{};
    SizeType pos{BufferSize - 1};

    bool negative{false};
    if constexpr (std::is_signed_v<T>) {
        if (value < 0) {
            negative = true;
            value = -value;
        }
    }

    if (value == 0) {
        buffer[pos--] = '0';
    } else {
        while (value > 0 && pos > 0) {
            buffer[pos--] = static_cast<char>('0' + (value % 10));
            value /= 10;
        }
    }

    if (negative && pos > 0) {
        buffer[pos--] = '-';
    }

    for (SizeType i{pos + 1}; i < BufferSize; ++i) {
        result.append(buffer[i]);
    }

    return result;
}

template<SizeType Width, Integral T>
[[nodiscard]] constexpr auto intToStringPadded(T value) noexcept -> StaticString<Width + 1> {
    StaticString<Width + 1> result{};
    std::array<char, Width> buffer{};

    for (auto& c : buffer) {
        c = '0';
    }

    SizeType pos{Width};
    T v{value};

    while (v > 0 && pos > 0) {
        buffer[--pos] = static_cast<char>('0' + (v % 10));
        v /= 10;
    }

    for (SizeType i{0}; i < Width; ++i) {
        result.append(buffer[i]);
    }

    return result;
}

[[nodiscard]] constexpr auto formatBarcode(BarcodeType barcode) noexcept -> BarcodeString {
    return intToStringPadded<BARCODE_DIGITS>(barcode);
}

} // namespace output_module::core
