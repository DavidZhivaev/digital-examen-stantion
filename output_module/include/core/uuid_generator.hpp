#pragma once

#include "types.hpp"
#include "static_string.hpp"
#include <array>
#include <cstdint>
#include <fcntl.h>
#include <unistd.h>

namespace output_module::core {

class UuidGenerator {
private:
    static constexpr std::array<char, 16> HEX_CHARS{
        '0', '1', '2', '3', '4', '5', '6', '7',
        '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'
    };

    [[nodiscard]] static auto getRandomBytes(ByteType* buffer, SizeType count) noexcept -> bool {
        int fd{::open("/dev/urandom", O_RDONLY)};
        if (fd < 0) [[unlikely]] {
            return false;
        }

        auto bytesRead{::read(fd, buffer, count)};
        ::close(fd);

        return bytesRead == static_cast<ssize_t>(count);
    }

    static constexpr auto byteToHex(ByteType b, char* out) noexcept -> void {
        out[0] = HEX_CHARS[(b >> 4) & 0x0F];
        out[1] = HEX_CHARS[b & 0x0F];
    }

public:
    [[nodiscard]] static auto generate() noexcept -> UuidString {
        std::array<ByteType, 16> bytes{};

        if (!getRandomBytes(bytes.data(), bytes.size())) [[unlikely]] {
            return UuidString{};
        }

        bytes[6] = (bytes[6] & 0x0F) | 0x40;
        bytes[8] = (bytes[8] & 0x3F) | 0x80;

        UuidString result{};
        std::array<char, 2> hex{};

        for (SizeType i{0}; i < 4; ++i) {
            byteToHex(bytes[i], hex.data());
            result.append(hex[0]);
            result.append(hex[1]);
        }
        result.append('-');

        for (SizeType i{4}; i < 6; ++i) {
            byteToHex(bytes[i], hex.data());
            result.append(hex[0]);
            result.append(hex[1]);
        }
        result.append('-');

        for (SizeType i{6}; i < 8; ++i) {
            byteToHex(bytes[i], hex.data());
            result.append(hex[0]);
            result.append(hex[1]);
        }
        result.append('-');

        for (SizeType i{8}; i < 10; ++i) {
            byteToHex(bytes[i], hex.data());
            result.append(hex[0]);
            result.append(hex[1]);
        }
        result.append('-');

        for (SizeType i{10}; i < 16; ++i) {
            byteToHex(bytes[i], hex.data());
            result.append(hex[0]);
            result.append(hex[1]);
        }

        return result;
    }
};

[[nodiscard]] inline auto generateUuid() noexcept -> UuidString {
    return UuidGenerator::generate();
}

} // namespace output_module::core
