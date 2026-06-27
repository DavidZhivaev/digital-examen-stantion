#pragma once

#include "types.hpp"
#include "static_string.hpp"
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <utility>

namespace output_module::core {

class FileHandle {
private:
    int fd_{-1};

public:
    FileHandle() noexcept = default;

    explicit FileHandle(int fd) noexcept : fd_{fd} {}

    template<SizeType N>
    explicit FileHandle(const StaticString<N>& path, int flags, mode_t mode = 0644) noexcept
        : fd_{::open(path.cStr(), flags, mode)} {}

    ~FileHandle() noexcept {
        close();
    }

    FileHandle(const FileHandle&) = delete;
    auto operator=(const FileHandle&) -> FileHandle& = delete;

    FileHandle(FileHandle&& other) noexcept : fd_{other.fd_} {
        other.fd_ = -1;
    }

    auto operator=(FileHandle&& other) noexcept -> FileHandle& {
        if (this != &other) [[likely]] {
            close();
            fd_ = other.fd_;
            other.fd_ = -1;
        }
        return *this;
    }

    [[nodiscard]] auto valid() const noexcept -> bool {
        return fd_ >= 0;
    }

    [[nodiscard]] auto get() const noexcept -> int {
        return fd_;
    }

    [[nodiscard]] auto release() noexcept -> int {
        int fd{fd_};
        fd_ = -1;
        return fd;
    }

    auto close() noexcept -> void {
        if (fd_ >= 0) [[likely]] {
            ::close(fd_);
            fd_ = -1;
        }
    }

    auto write(const void* data, SizeType size) const noexcept -> ssize_t {
        if (fd_ < 0) [[unlikely]] {
            return -1;
        }
        return ::write(fd_, data, size);
    }

    auto read(void* buffer, SizeType size) const noexcept -> ssize_t {
        if (fd_ < 0) [[unlikely]] {
            return -1;
        }
        return ::read(fd_, buffer, size);
    }

    auto seek(off_t offset, int whence = SEEK_SET) const noexcept -> off_t {
        if (fd_ < 0) [[unlikely]] {
            return -1;
        }
        return ::lseek(fd_, offset, whence);
    }

    [[nodiscard]] auto size() const noexcept -> off_t {
        if (fd_ < 0) [[unlikely]] {
            return -1;
        }
        struct stat st{};
        if (::fstat(fd_, &st) != 0) [[unlikely]] {
            return -1;
        }
        return st.st_size;
    }

    auto sync() const noexcept -> bool {
        if (fd_ < 0) [[unlikely]] {
            return false;
        }
        return ::fsync(fd_) == 0;
    }
};

template<SizeType PathSize>
[[nodiscard]] inline auto createFile(const StaticString<PathSize>& path) noexcept -> FileHandle {
    return FileHandle{path, O_WRONLY | O_CREAT | O_TRUNC, 0644};
}

template<SizeType PathSize>
[[nodiscard]] inline auto openFileRead(const StaticString<PathSize>& path) noexcept -> FileHandle {
    return FileHandle{path, O_RDONLY};
}

template<SizeType PathSize>
[[nodiscard]] inline auto fileExists(const StaticString<PathSize>& path) noexcept -> bool {
    struct stat st{};
    return ::stat(path.cStr(), &st) == 0;
}

template<SizeType PathSize>
[[nodiscard]] inline auto createDirectory(const StaticString<PathSize>& path) noexcept -> bool {
    return ::mkdir(path.cStr(), 0755) == 0 || errno == EEXIST;
}

} // namespace output_module::core
