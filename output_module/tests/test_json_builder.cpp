#include "../include/formatters/json_builder.hpp"
#include "../include/core/sheet_data.hpp"
#include <cstdio>
#include <cstring>

using namespace output_module::core;
using namespace output_module::formatters;

auto testBasicObject() -> bool {
    JsonBuilder<1024> builder{};

    builder.beginObject();
    builder.keyValue("name", "test");
    builder.keyValue("value", static_cast<long>(42));
    builder.endObject();

    auto* data{reinterpret_cast<const char*>(builder.data())};

    if (std::strstr(data, "\"name\"") == nullptr) {
        return false;
    }

    if (std::strstr(data, "\"test\"") == nullptr) {
        return false;
    }

    return true;
}

auto testNestedObject() -> bool {
    JsonBuilder<1024> builder{};

    builder.beginObject();
    builder.keyBeginObject("outer");
    builder.keyValue("inner", static_cast<long>(123));
    builder.endObject();
    builder.endObject();

    auto* data{reinterpret_cast<const char*>(builder.data())};

    if (std::strstr(data, "\"outer\"") == nullptr) {
        return false;
    }

    if (std::strstr(data, "\"inner\"") == nullptr) {
        return false;
    }

    return true;
}

auto testChainResultsJson() -> bool {
    WorkChain chain{};
    chain.workId = UuidString{"test-uuid"};
    chain.titleBarcode = 1234567890123LL;
    chain.chainValid = true;

    SheetData sheet1{};
    sheet1.barcode = 1234567890123LL;
    sheet1.type = SheetType::Titul;
    sheet1.valid = true;
    chain.sheets.pushBack(sheet1);

    SheetData sheet2{};
    sheet2.barcode = 1234567890124LL;
    sheet2.type = SheetType::Blan1;
    sheet2.valid = true;
    chain.sheets.pushBack(sheet2);

    SheetData sheet3{};
    sheet3.barcode = 1234567890125LL;
    sheet3.type = SheetType::Blan2;
    sheet3.valid = true;
    chain.sheets.pushBack(sheet3);

    auto builder{buildResultsJson(chain)};

    auto* data{reinterpret_cast<const char*>(builder.data())};

    if (std::strstr(data, "\"1234567890123\"") == nullptr) {
        std::printf("Missing title barcode key\n");
        return false;
    }

    if (std::strstr(data, "\"chain\"") == nullptr) {
        std::printf("Missing chain array\n");
        return false;
    }

    if (std::strstr(data, "\"sheet_count\"") == nullptr) {
        std::printf("Missing sheet_count\n");
        return false;
    }

    if (std::strstr(data, "\"chain_valid\"") == nullptr) {
        std::printf("Missing chain_valid\n");
        return false;
    }

    if (std::strstr(data, "\"1234567890124\"") == nullptr) {
        std::printf("Missing second sheet barcode\n");
        return false;
    }

    if (std::strstr(data, "\"1234567890125\"") == nullptr) {
        std::printf("Missing third sheet barcode\n");
        return false;
    }

    return true;
}

auto main() -> int {
    int passed{0};
    int failed{0};

    if (testBasicObject()) {
        ++passed;
        std::printf("[PASS] testBasicObject\n");
    } else {
        ++failed;
        std::printf("[FAIL] testBasicObject\n");
    }

    if (testNestedObject()) {
        ++passed;
        std::printf("[PASS] testNestedObject\n");
    } else {
        ++failed;
        std::printf("[FAIL] testNestedObject\n");
    }

    if (testChainResultsJson()) {
        ++passed;
        std::printf("[PASS] testChainResultsJson\n");
    } else {
        ++failed;
        std::printf("[FAIL] testChainResultsJson\n");
    }

    std::printf("\nResults: %d passed, %d failed\n", passed, failed);
    return failed > 0 ? 1 : 0;
}
