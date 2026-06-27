#include "ScannerHAL.hpp"
#include <iostream>
#include <string>
#include <cstdlib>
#include <array>

#include <pybind11/embed.h>
#include <pybind11/numpy.h>

namespace py = pybind11;

class alignas(64) PythonInterpreterGuard final {
private:
	py::scoped_interpreter m_interpreter{};

public:
	PythonInterpreterGuard() {
		py::module_::import("sys").attr("path").attr("append")("..");
	}

	PythonInterpreterGuard(const PythonInterpreterGuard&) = delete;
	PythonInterpreterGuard& operator=(const PythonInterpreterGuard&) = delete;
	PythonInterpreterGuard(PythonInterpreterGuard&&) = delete;
	PythonInterpreterGuard& operator=(PythonInterpreterGuard&&) = delete;

	~PythonInterpreterGuard() = default;
};

void ProcessScannedBlank(const cv::Mat& documentFrame) noexcept {
	if (documentFrame.empty()) [[unlikely]] {
		std::cerr << "[Core] Пустой кадр со сканера!\n";
		return;
	}

	try {
		py::capsule bufferManager{
			documentFrame.data,
			[](void*) noexcept {}
		};

		std::array<size_t, 3> shape{
			static_cast<size_t>(documentFrame.rows),
			static_cast<size_t>(documentFrame.cols),
			static_cast<size_t>(documentFrame.channels())
		};

		std::array<size_t, 3> strides{
			static_cast<size_t>(documentFrame.step[0]),
			static_cast<size_t>(documentFrame.step[1]),
			static_cast<size_t>(documentFrame.elemSize())
		};

		py::array_t<unsigned char> numpyArray{
			shape,
			strides,
			documentFrame.data,
			bufferManager
		};

		py::object pythonScript{py::module_::import("recognizer")};

		py::object pythonResult{pythonScript.attr("some_func")(numpyArray)};

		std::string cppResultString{pythonResult.cast<std::string>()};
		std::cout << "[Core C++] Результат: " << cppResultString << '\n';

	} catch (const py::error_already_set& e) {
		std::cerr << "[Python Error] Ошибка в модели анализа бланков: " << e.what() << '\n';
	} catch (const std::exception& e) {
		std::cerr << "[Exception] Непредвиденная ошибка: " << e.what() << '\n';
	} catch (...) {
		std::cerr << "[Fatal] Неизвестная ошибка в ProcessScannedBlank\n";
	}
}

int main() {
	try {
		PythonInterpreterGuard pythonVM{};

		HardwareScanner scannerDevice{
#if defined(_WIN32) || defined(_WIN64)
			HardwareScanner::ScannerAPI::TWAIN
#elif defined(__linux__)
			HardwareScanner::ScannerAPI::SANE
#endif
		};

		std::vector<std::string> foundScanners{scannerDevice.GetAllAvailableScanners()};

		if (foundScanners.empty()) [[unlikely]] {
			std::cerr << "[Error] TWAIN/SANE не обнаружены, установите драйверы от производителя.\n";
			return EXIT_FAILURE;
		}

		std::cout << "На данном устройстве доступны сканнеры:\n";
		for (size_t i{0}; i < foundScanners.size(); ++i) {
			std::cout << "[" << i << "] -> " << foundScanners[i] << '\n';
		}

		const std::string& chosenScanner{foundScanners[0]};
		std::cout << "Динамически установленный индекс сканнера: " << chosenScanner << "...\n";

		if (!scannerDevice.OpenConnection(chosenScanner)) [[unlikely]] {
			std::cerr << "[Error] Не удалось установить соединение с " << chosenScanner << '\n';
			return EXIT_FAILURE;
		}

		std::cout << "Сканнер готов к работе. Запускаю потоковую обработку...\n";
		scannerDevice.StartCaptureLoop(ProcessScannedBlank);

		scannerDevice.CloseConnection();

		return EXIT_SUCCESS;

	} catch (const py::error_already_set& e) {
		std::cerr << "[Fatal Python Error] " << e.what() << '\n';
		return EXIT_FAILURE;
	} catch (const std::exception& e) {
		std::cerr << "[Fatal Exception] " << e.what() << '\n';
		return EXIT_FAILURE;
	} catch (...) {
		std::cerr << "[Fatal] Неизвестная критическая ошибка\n";
		return EXIT_FAILURE;
	}
}
