#include "../include/output_generator.hpp"
#include <cstdio>

using namespace output_module;
using namespace output_module::core;

auto main(int argc, char* argv[]) -> int {
    if (argc < 3) {
        std::printf("Usage: %s <output_dir> <image1.jpg> [image2.jpg ...]\n", argv[0]);
        return 1;
    }

    PathString outputDir{argv[1]};

    OutputGenerator generator{outputDir.cStr()};

    WorkChain chain{};
    chain.workId = UuidString{"550e8400-e29b-41d4-a716-446655440000"};
    chain.chainValid = true;

    for (int i{2}; i < argc; ++i) {
        SheetData sheet{};
        sheet.imagePath = PathString{argv[i]};
        sheet.barcode = 1234567890123LL + static_cast<BarcodeType>(i - 2);
        sheet.orderInChain = static_cast<SizeType>(i - 2);

        if (i == 2) {
            sheet.type = SheetType::Titul;
            chain.titleBarcode = sheet.barcode;
        } else if (i == 3) {
            sheet.type = SheetType::Blan1;
        } else {
            sheet.type = SheetType::Blan2;
        }

        sheet.valid = true;
        chain.sheets.pushBack(sheet);
    }

    auto result{generator.createPackage(chain)};

    if (result.ok()) {
        std::printf("Success!\n");
        std::printf("ZIP: %s\n", result.zipPath.cStr());
        std::printf("PDF: %s\n", result.pdfFilename.cStr());
        std::printf("Work ID: %s\n", result.workId.cStr());
        std::printf("Title barcode: %lld\n", static_cast<long long>(result.titleBarcode));
        std::printf("Sheets: %zu\n", result.sheetCount);
        std::printf("Chain valid: %s\n", result.chainValid ? "true" : "false");
        return 0;
    } else {
        std::printf("Error: %d\n", result.errorCode());
        return 1;
    }
}
