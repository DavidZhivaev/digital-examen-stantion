#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "../include/output_generator.hpp"

namespace py = pybind11;
using namespace output_module;
using namespace output_module::core;

namespace {

class PyOutputGenerator {
private:
    OutputGenerator generator_{};
    PathString outputDir_{};

public:
    PyOutputGenerator() noexcept = default;

    explicit PyOutputGenerator(const std::string& outputDir) noexcept
        : generator_{outputDir.c_str()}
        , outputDir_{outputDir.c_str()} {}

    auto setOutputDir(const std::string& dir) noexcept -> void {
        outputDir_.clear();
        outputDir_.append(dir.c_str());
        generator_.setOutputDir(dir.c_str());
    }

    auto createPackage(
        const std::string& workId,
        std::int64_t titleBarcode,
        const std::vector<std::tuple<std::string, std::int64_t, int>>& sheets,
        bool chainValid
    ) -> py::dict {
        WorkChain chain{};

        chain.workId = UuidString{workId.c_str()};
        chain.titleBarcode = titleBarcode;
        chain.chainValid = chainValid;

        SizeType order{0};
        for (const auto& [path, barcode, typeInt] : sheets) {
            SheetData sheet{};
            sheet.imagePath = PathString{path.c_str()};
            sheet.barcode = barcode;
            sheet.type = static_cast<SheetType>(typeInt);
            sheet.orderInChain = order++;
            sheet.valid = true;
            chain.sheets.pushBack(sheet);
        }

        auto result{generator_.createPackage(chain)};

        py::dict pyResult{};
        pyResult["ok"] = result.ok();
        pyResult["status"] = static_cast<int>(result.status);
        pyResult["zip_path"] = std::string{result.zipPath.cStr()};
        pyResult["pdf_filename"] = std::string{result.pdfFilename.cStr()};
        pyResult["work_id"] = std::string{result.workId.cStr()};
        pyResult["title_barcode"] = result.titleBarcode;
        pyResult["sheet_count"] = result.sheetCount;
        pyResult["chain_valid"] = result.chainValid;

        return pyResult;
    }
};

}

PYBIND11_MODULE(output_generator_cpp, m) {
    m.doc() = "Output generator module for exam sheet processing";

    py::enum_<SheetType>(m, "SheetType")
        .value("Unknown", SheetType::Unknown)
        .value("Titul", SheetType::Titul)
        .value("Blan1", SheetType::Blan1)
        .value("Blan2", SheetType::Blan2)
        .value("Additional", SheetType::Additional);

    py::enum_<ResultStatus>(m, "ResultStatus")
        .value("Success", ResultStatus::Success)
        .value("ErrorNoSheets", ResultStatus::ErrorNoSheets)
        .value("ErrorNoBarcode", ResultStatus::ErrorNoBarcode)
        .value("ErrorPdfCreation", ResultStatus::ErrorPdfCreation)
        .value("ErrorZipCreation", ResultStatus::ErrorZipCreation)
        .value("ErrorFileWrite", ResultStatus::ErrorFileWrite)
        .value("ErrorInvalidInput", ResultStatus::ErrorInvalidInput);

    py::class_<PyOutputGenerator>(m, "OutputGenerator")
        .def(py::init<>())
        .def(py::init<const std::string&>(), py::arg("output_dir"))
        .def("set_output_dir", &PyOutputGenerator::setOutputDir, py::arg("dir"))
        .def("create_package", &PyOutputGenerator::createPackage,
             py::arg("work_id"),
             py::arg("title_barcode"),
             py::arg("sheets"),
             py::arg("chain_valid") = true);

    m.def("create_work_package", [](
        const std::string& outputDir,
        const std::string& workId,
        std::int64_t titleBarcode,
        const std::vector<std::tuple<std::string, std::int64_t, int>>& sheets,
        bool chainValid
    ) -> py::dict {
        PyOutputGenerator generator{outputDir};
        return generator.createPackage(workId, titleBarcode, sheets, chainValid);
    },
    py::arg("output_dir"),
    py::arg("work_id"),
    py::arg("title_barcode"),
    py::arg("sheets"),
    py::arg("chain_valid") = true);
}
