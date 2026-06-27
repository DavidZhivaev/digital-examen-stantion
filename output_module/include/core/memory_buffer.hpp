#pragma once

#include "types.hpp"
#include <array>
#include <cstring>

namespace output_module::core {

template<SizeType Capacity>
    requires PowerOfTwo<Capacity>
class alignas(CACHE_LINE_SIZE) MemoryBuffer {
public:
    using ValueType = ByteType;
    using SizeType = core::SizeType;

private:
    std::array<ValueType, Capacity> data_{};
    SizeType writePos_{0};
    SizeType readPos_{0};

    static constexpr SizeType MASK{Capacity - 1};

public:
    constexpr MemoryBuffer() noexcept = default;

    [[nodiscard]] constexpr auto capacity() const noexcept -> SizeType {
        return Capacity;
    }

    [[nodiscard]] constexpr auto size() const noexcept -> SizeType {
        return writePos_ - readPos_;
    }

    [[nodiscard]] constexpr auto available() const noexcept -> SizeType {
        return Capacity - size();
    }

    [[nodiscard]] constexpr auto empty() const noexcept -> bool {
        return writePos_ == readPos_;
    }

    [[nodiscard]] constexpr auto full() const noexcept -> bool {
        return size() >= Capacity;
    }

    [[nodiscard]] constexpr auto data() noexcept -> ValueType* {
        return data_.data();
    }

    [[nodiscard]] constexpr auto data() const noexcept -> const ValueType* {
        return data_.data();
    }

    [[nodiscard]] constexpr auto writePosition() const noexcept -> SizeType {
        return writePos_;
    }

    constexpr auto clear() noexcept -> void {
        writePos_ = 0;
        readPos_ = 0;
    }

    constexpr auto write(ValueType byte) noexcept -> bool {
        if (size() < Capacity) [[likely]] {
            data_[writePos_ & MASK] = byte;
            ++writePos_;
            return true;
        }
        return false;
    }

    constexpr auto write(const void* src, SizeType len) noexcept -> SizeType {
        const auto* bytes{static_cast<const ValueType*>(src)};
        SizeType written{0};

        while (written < len && size() < Capacity) {
            data_[writePos_ & MASK] = bytes[written];
            ++writePos_;
            ++written;
        }

        return written;
    }

    template<SizeType N>
    constexpr auto write(const std::array<ValueType, N>& arr) noexcept -> SizeType {
        return write(arr.data(), N);
    }

    constexpr auto writeRaw(const void* src, SizeType len) noexcept -> SizeType {
        if (writePos_ + len > Capacity) [[unlikely]] {
            return 0;
        }
        std::memcpy(data_.data() + writePos_, src, len);
        writePos_ += len;
        return len;
    }

    [[nodiscard]] constexpr auto read() noexcept -> ValueType {
        if (readPos_ < writePos_) [[likely]] {
            return data_[readPos_++ & MASK];
        }
        return 0;
    }

    constexpr auto read(void* dst, SizeType len) noexcept -> SizeType {
        auto* bytes{static_cast<ValueType*>(dst)};
        SizeType bytesRead{0};

        while (bytesRead < len && readPos_ < writePos_) {
            bytes[bytesRead] = data_[readPos_ & MASK];
            ++readPos_;
            ++bytesRead;
        }

        return bytesRead;
    }

    [[nodiscard]] constexpr auto peek(SizeType offset = 0) const noexcept -> ValueType {
        if (readPos_ + offset < writePos_) [[likely]] {
            return data_[(readPos_ + offset) & MASK];
        }
        return 0;
    }

    constexpr auto skip(SizeType count) noexcept -> SizeType {
        SizeType toSkip{count};
        if (toSkip > size()) {
            toSkip = size();
        }
        readPos_ += toSkip;
        return toSkip;
    }

    constexpr auto resetRead() noexcept -> void {
        readPos_ = 0;
    }
};

template<SizeType Capacity>
class alignas(CACHE_LINE_SIZE) LinearBuffer {
public:
    using ValueType = ByteType;
    using SizeType = core::SizeType;

private:
    std::array<ValueType, Capacity> data_{};
    SizeType size_{0};

public:
    constexpr LinearBuffer() noexcept = default;

    [[nodiscard]] constexpr auto capacity() const noexcept -> SizeType {
        return Capacity;
    }

    [[nodiscard]] constexpr auto size() const noexcept -> SizeType {
        return size_;
    }

    [[nodiscard]] constexpr auto available() const noexcept -> SizeType {
        return Capacity - size_;
    }

    [[nodiscard]] constexpr auto empty() const noexcept -> bool {
        return size_ == 0;
    }

    [[nodiscard]] constexpr auto data() noexcept -> ValueType* {
        return data_.data();
    }

    [[nodiscard]] constexpr auto data() const noexcept -> const ValueType* {
        return data_.data();
    }

    constexpr auto clear() noexcept -> void {
        size_ = 0;
    }

    constexpr auto append(ValueType byte) noexcept -> bool {
        if (size_ < Capacity) [[likely]] {
            data_[size_++] = byte;
            return true;
        }
        return false;
    }

    constexpr auto append(const void* src, SizeType len) noexcept -> SizeType {
        SizeType toWrite{len};
        if (size_ + toWrite > Capacity) {
            toWrite = Capacity - size_;
        }
        if (toWrite > 0) [[likely]] {
            std::memcpy(data_.data() + size_, src, toWrite);
            size_ += toWrite;
        }
        return toWrite;
    }

    constexpr auto append(const char* str) noexcept -> SizeType {
        SizeType written{0};
        while (str[written] != '\0' && size_ < Capacity) {
            data_[size_++] = static_cast<ValueType>(str[written++]);
        }
        return written;
    }

    template<SizeType N>
    constexpr auto append(const StaticString<N>& str) noexcept -> SizeType {
        return append(str.data(), str.size());
    }
};

} // namespace output_module::core
