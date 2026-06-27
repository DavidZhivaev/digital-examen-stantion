#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>
#include "ScannerHAL.hpp"

namespace py = pybind11;

class alignas(64) PyScannerWrapper final {
private:
	HardwareScanner m_scanner{};
	bool m_connected{false};

public:
	PyScannerWrapper() noexcept = default;

	PyScannerWrapper(const PyScannerWrapper&) = delete;
	PyScannerWrapper& operator=(const PyScannerWrapper&) = delete;
	PyScannerWrapper(PyScannerWrapper&&) = delete;
	PyScannerWrapper& operator=(PyScannerWrapper&&) = delete;

	~PyScannerWrapper() noexcept {
		if (m_connected) [[unlikely]] {
			m_scanner.CloseConnection();
		}
	}

	[[nodiscard]] std::vector<std::string> list_scanners() {
		return m_scanner.GetAllAvailableScanners();
	}

	[[nodiscard]] bool connect(const std::string& device) {
		if (m_connected) [[unlikely]] {
			m_scanner.CloseConnection();
		}
		m_connected = m_scanner.OpenConnection(device);
		return m_connected;
	}

	void disconnect() noexcept {
		if (m_connected) [[likely]] {
			m_scanner.CloseConnection();
			m_connected = false;
		}
	}

	[[nodiscard]] py::array_t<uint8_t> scan_page() {
		cv::Mat frame{};
		bool gotFrame{false};

		m_scanner.StartCaptureLoop([&frame, &gotFrame](const cv::Mat& scanned) {
			if (!gotFrame) [[likely]] {
				frame = scanned.clone();
				gotFrame = true;
			}
		});

		if (frame.empty()) [[unlikely]] {
			return py::array_t<uint8_t>();
		}

		std::vector<ssize_t> shape{frame.rows, frame.cols, frame.channels()};
		std::vector<ssize_t> strides{
			static_cast<ssize_t>(frame.step[0]),
			static_cast<ssize_t>(frame.step[1]),
			static_cast<ssize_t>(frame.elemSize1())
		};

		auto result = py::array_t<uint8_t>(shape, strides);
		std::memcpy(result.mutable_data(), frame.data, frame.total() * frame.elemSize());
		return result;
	}

	[[nodiscard]] std::vector<py::array_t<uint8_t>> scan_batch() {
		std::vector<py::array_t<uint8_t>> results{};

		m_scanner.StartCaptureLoop([&results](const cv::Mat& scanned) {
			if (scanned.empty()) [[unlikely]] {
				return;
			}

			std::vector<ssize_t> shape{scanned.rows, scanned.cols, scanned.channels()};
			std::vector<ssize_t> strides{
				static_cast<ssize_t>(scanned.step[0]),
				static_cast<ssize_t>(scanned.step[1]),
				static_cast<ssize_t>(scanned.elemSize1())
			};

			auto arr = py::array_t<uint8_t>(shape, strides);
			std::memcpy(arr.mutable_data(), scanned.data, scanned.total() * scanned.elemSize());
			results.push_back(std::move(arr));
		});

		return results;
	}
};

PYBIND11_MODULE(scanner_hal, m) {
	py::class_<PyScannerWrapper>(m, "Scanner")
		.def(py::init<>())
		.def("list_scanners", &PyScannerWrapper::list_scanners)
		.def("connect", &PyScannerWrapper::connect, py::arg("device"))
		.def("disconnect", &PyScannerWrapper::disconnect)
		.def("scan_page", &PyScannerWrapper::scan_page)
		.def("scan_batch", &PyScannerWrapper::scan_batch);
}
