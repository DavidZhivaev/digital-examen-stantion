#include "../include/core/static_string.hpp"
#include <cstdio>
#include <cstring>

using namespace output_module::core;

auto testConstruction() -> bool {
    StaticString<64> s1{};
    if (s1.size() != 0) return false;
    if (!s1.empty()) return false;

    StaticString<64> s2{"hello"};
    if (s2.size() != 5) return false;
    if (std::strcmp(s2.cStr(), "hello") != 0) return false;

    return true;
}

auto testAppend() -> bool {
    StaticString<64> s{};

    s.append('a');
    if (s.size() != 1) return false;

    s.append("bcd");
    if (s.size() != 4) return false;
    if (std::strcmp(s.cStr(), "abcd") != 0) return false;

    return true;
}

auto testBarcodeFormat() -> bool {
    auto formatted{formatBarcode(1234567890123LL)};
    if (formatted.size() != 13) return false;
    if (std::strcmp(formatted.cStr(), "1234567890123") != 0) return false;

    auto formatted2{formatBarcode(1LL)};
    if (formatted2.size() != 13) return false;
    if (std::strcmp(formatted2.cStr(), "0000000000001") != 0) return false;

    return true;
}

auto testIntToString() -> bool {
    auto s1{intToString(12345)};
    if (std::strcmp(s1.cStr(), "12345") != 0) return false;

    auto s2{intToString(-42)};
    if (std::strcmp(s2.cStr(), "-42") != 0) return false;

    auto s3{intToString(0)};
    if (std::strcmp(s3.cStr(), "0") != 0) return false;

    return true;
}

auto main() -> int {
    int passed{0};
    int failed{0};

    if (testConstruction()) {
        ++passed;
        std::printf("[PASS] testConstruction\n");
    } else {
        ++failed;
        std::printf("[FAIL] testConstruction\n");
    }

    if (testAppend()) {
        ++passed;
        std::printf("[PASS] testAppend\n");
    } else {
        ++failed;
        std::printf("[FAIL] testAppend\n");
    }

    if (testBarcodeFormat()) {
        ++passed;
        std::printf("[PASS] testBarcodeFormat\n");
    } else {
        ++failed;
        std::printf("[FAIL] testBarcodeFormat\n");
    }

    if (testIntToString()) {
        ++passed;
        std::printf("[PASS] testIntToString\n");
    } else {
        ++failed;
        std::printf("[FAIL] testIntToString\n");
    }

    std::printf("\nResults: %d passed, %d failed\n", passed, failed);
    return failed > 0 ? 1 : 0;
}
