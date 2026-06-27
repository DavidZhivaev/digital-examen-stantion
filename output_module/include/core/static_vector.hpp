#pragma once

#include "types.hpp"
#include <array>
#include <utility>

namespace output_module::core {

template<typename T, SizeType Capacity>
    requires (Capacity > 0) && Trivial<T>
class alignas(CACHE_LINE_SIZE) StaticVector {
public:
    using ValueType = T;
    using SizeType = core::SizeType;
    using Iterator = T*;
    using ConstIterator = const T*;
    using Reference = T&;
    using ConstReference = const T&;

private:
    std::array<T, Capacity> data_{};
    SizeType size_{0};

public:
    constexpr StaticVector() noexcept = default;

    [[nodiscard]] constexpr auto size() const noexcept -> SizeType {
        return size_;
    }

    [[nodiscard]] constexpr auto capacity() const noexcept -> SizeType {
        return Capacity;
    }

    [[nodiscard]] constexpr auto empty() const noexcept -> bool {
        return size_ == 0;
    }

    [[nodiscard]] constexpr auto full() const noexcept -> bool {
        return size_ >= Capacity;
    }

    [[nodiscard]] constexpr auto data() noexcept -> T* {
        return data_.data();
    }

    [[nodiscard]] constexpr auto data() const noexcept -> const T* {
        return data_.data();
    }

    [[nodiscard]] constexpr auto operator[](SizeType index) noexcept -> Reference {
        return data_[index];
    }

    [[nodiscard]] constexpr auto operator[](SizeType index) const noexcept -> ConstReference {
        return data_[index];
    }

    [[nodiscard]] constexpr auto front() noexcept -> Reference {
        return data_[0];
    }

    [[nodiscard]] constexpr auto front() const noexcept -> ConstReference {
        return data_[0];
    }

    [[nodiscard]] constexpr auto back() noexcept -> Reference {
        return data_[size_ - 1];
    }

    [[nodiscard]] constexpr auto back() const noexcept -> ConstReference {
        return data_[size_ - 1];
    }

    constexpr auto pushBack(const T& value) noexcept -> bool {
        if (size_ < Capacity) [[likely]] {
            data_[size_++] = value;
            return true;
        }
        return false;
    }

    constexpr auto pushBack(T&& value) noexcept -> bool {
        if (size_ < Capacity) [[likely]] {
            data_[size_++] = std::move(value);
            return true;
        }
        return false;
    }

    template<typename... Args>
    constexpr auto emplaceBack(Args&&... args) noexcept -> bool {
        if (size_ < Capacity) [[likely]] {
            data_[size_++] = T{std::forward<Args>(args)...};
            return true;
        }
        return false;
    }

    constexpr auto popBack() noexcept -> void {
        if (size_ > 0) [[likely]] {
            --size_;
        }
    }

    constexpr auto clear() noexcept -> void {
        size_ = 0;
    }

    [[nodiscard]] constexpr auto begin() noexcept -> Iterator {
        return data_.data();
    }

    [[nodiscard]] constexpr auto end() noexcept -> Iterator {
        return data_.data() + size_;
    }

    [[nodiscard]] constexpr auto begin() const noexcept -> ConstIterator {
        return data_.data();
    }

    [[nodiscard]] constexpr auto end() const noexcept -> ConstIterator {
        return data_.data() + size_;
    }

    [[nodiscard]] constexpr auto cbegin() const noexcept -> ConstIterator {
        return data_.data();
    }

    [[nodiscard]] constexpr auto cend() const noexcept -> ConstIterator {
        return data_.data() + size_;
    }
};

} // namespace output_module::core
