#pragma once

#include "types.hpp"
#include <array>
#include <utility>

namespace output_module::core {

template<typename K, typename V, SizeType Capacity>
    requires (Capacity > 0) && Trivial<K> && Trivial<V>
class alignas(CACHE_LINE_SIZE) PairStorage {
public:
    struct Entry {
        K key{};
        V value{};
        bool occupied{false};
    };

    using SizeType = core::SizeType;

private:
    std::array<Entry, Capacity> entries_{};
    SizeType size_{0};

public:
    constexpr PairStorage() noexcept = default;

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

    constexpr auto insert(const K& key, const V& value) noexcept -> bool {
        if (size_ >= Capacity) [[unlikely]] {
            return false;
        }

        for (auto& entry : entries_) {
            if (!entry.occupied) {
                entry.key = key;
                entry.value = value;
                entry.occupied = true;
                ++size_;
                return true;
            }
        }

        return false;
    }

    [[nodiscard]] constexpr auto find(const K& key) const noexcept -> const V* {
        for (const auto& entry : entries_) {
            if (entry.occupied && entry.key == key) [[unlikely]] {
                return &entry.value;
            }
        }
        return nullptr;
    }

    [[nodiscard]] constexpr auto find(const K& key) noexcept -> V* {
        for (auto& entry : entries_) {
            if (entry.occupied && entry.key == key) [[unlikely]] {
                return &entry.value;
            }
        }
        return nullptr;
    }

    constexpr auto remove(const K& key) noexcept -> bool {
        for (auto& entry : entries_) {
            if (entry.occupied && entry.key == key) {
                entry.occupied = false;
                --size_;
                return true;
            }
        }
        return false;
    }

    constexpr auto clear() noexcept -> void {
        for (auto& entry : entries_) {
            entry.occupied = false;
        }
        size_ = 0;
    }

    template<typename Func>
    constexpr auto forEach(Func&& func) const noexcept -> void {
        for (const auto& entry : entries_) {
            if (entry.occupied) {
                func(entry.key, entry.value);
            }
        }
    }

    [[nodiscard]] constexpr auto begin() noexcept -> Entry* {
        return entries_.data();
    }

    [[nodiscard]] constexpr auto end() noexcept -> Entry* {
        return entries_.data() + Capacity;
    }

    [[nodiscard]] constexpr auto begin() const noexcept -> const Entry* {
        return entries_.data();
    }

    [[nodiscard]] constexpr auto end() const noexcept -> const Entry* {
        return entries_.data() + Capacity;
    }
};

} // namespace output_module::core
