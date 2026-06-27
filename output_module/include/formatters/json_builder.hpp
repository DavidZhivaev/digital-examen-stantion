#pragma once

#include "../core/types.hpp"
#include "../core/static_string.hpp"
#include "../core/memory_buffer.hpp"
#include "../core/sheet_data.hpp"

namespace output_module::formatters {

using namespace core;

inline constexpr SizeType JSON_BUFFER_SIZE{1ULL << 16};

template<SizeType BufferSize = JSON_BUFFER_SIZE>
class alignas(CACHE_LINE_SIZE) JsonBuilder {
private:
    LinearBuffer<BufferSize> buffer_{};
    SizeType indentLevel_{0};
    bool needComma_{false};

    static constexpr std::array<char, 2> INDENT_CHARS{' ', ' '};

    constexpr auto writeIndent() noexcept -> void {
        for (SizeType i{0}; i < indentLevel_; ++i) {
            buffer_.append(INDENT_CHARS.data(), INDENT_CHARS.size());
        }
    }

    constexpr auto writeCommaIfNeeded() noexcept -> void {
        if (needComma_) [[likely]] {
            buffer_.append(',');
            buffer_.append('\n');
        }
    }

public:
    constexpr JsonBuilder() noexcept = default;

    [[nodiscard]] constexpr auto data() const noexcept -> const ByteType* {
        return buffer_.data();
    }

    [[nodiscard]] constexpr auto size() const noexcept -> SizeType {
        return buffer_.size();
    }

    constexpr auto clear() noexcept -> void {
        buffer_.clear();
        indentLevel_ = 0;
        needComma_ = false;
    }

    constexpr auto beginObject() noexcept -> JsonBuilder& {
        writeCommaIfNeeded();
        buffer_.append('{');
        buffer_.append('\n');
        ++indentLevel_;
        needComma_ = false;
        return *this;
    }

    constexpr auto beginObjectInline() noexcept -> JsonBuilder& {
        writeCommaIfNeeded();
        writeIndent();
        buffer_.append('{');
        buffer_.append('\n');
        ++indentLevel_;
        needComma_ = false;
        return *this;
    }

    constexpr auto endObject() noexcept -> JsonBuilder& {
        buffer_.append('\n');
        --indentLevel_;
        writeIndent();
        buffer_.append('}');
        needComma_ = true;
        return *this;
    }

    constexpr auto beginArray() noexcept -> JsonBuilder& {
        buffer_.append('[');
        buffer_.append('\n');
        ++indentLevel_;
        needComma_ = false;
        return *this;
    }

    constexpr auto beginArrayInline() noexcept -> JsonBuilder& {
        buffer_.append('[');
        needComma_ = false;
        return *this;
    }

    constexpr auto endArray() noexcept -> JsonBuilder& {
        buffer_.append('\n');
        --indentLevel_;
        writeIndent();
        buffer_.append(']');
        needComma_ = true;
        return *this;
    }

    constexpr auto endArrayInline() noexcept -> JsonBuilder& {
        buffer_.append(']');
        needComma_ = true;
        return *this;
    }

    template<SizeType N>
    constexpr auto key(const StaticString<N>& name) noexcept -> JsonBuilder& {
        writeCommaIfNeeded();
        writeIndent();
        buffer_.append('"');
        buffer_.append(name);
        buffer_.append('"');
        buffer_.append(':');
        buffer_.append(' ');
        needComma_ = false;
        return *this;
    }

    constexpr auto key(const char* name) noexcept -> JsonBuilder& {
        writeCommaIfNeeded();
        writeIndent();
        buffer_.append('"');
        buffer_.append(name);
        buffer_.append('"');
        buffer_.append(':');
        buffer_.append(' ');
        needComma_ = false;
        return *this;
    }

    template<SizeType N>
    constexpr auto keyBeginObject(const StaticString<N>& name) noexcept -> JsonBuilder& {
        writeCommaIfNeeded();
        writeIndent();
        buffer_.append('"');
        buffer_.append(name);
        buffer_.append('"');
        buffer_.append(':');
        buffer_.append(' ');
        buffer_.append('{');
        buffer_.append('\n');
        ++indentLevel_;
        needComma_ = false;
        return *this;
    }

    constexpr auto keyBeginObject(const char* name) noexcept -> JsonBuilder& {
        writeCommaIfNeeded();
        writeIndent();
        buffer_.append('"');
        buffer_.append(name);
        buffer_.append('"');
        buffer_.append(':');
        buffer_.append(' ');
        buffer_.append('{');
        buffer_.append('\n');
        ++indentLevel_;
        needComma_ = false;
        return *this;
    }

    template<SizeType N>
    constexpr auto valueString(const StaticString<N>& value) noexcept -> JsonBuilder& {
        buffer_.append('"');
        buffer_.append(value);
        buffer_.append('"');
        needComma_ = true;
        return *this;
    }

    constexpr auto valueString(const char* value) noexcept -> JsonBuilder& {
        buffer_.append('"');
        buffer_.append(value);
        buffer_.append('"');
        needComma_ = true;
        return *this;
    }

    constexpr auto valueInt(BarcodeType value) noexcept -> JsonBuilder& {
        auto str{intToString(value)};
        buffer_.append(str);
        needComma_ = true;
        return *this;
    }

    constexpr auto valueBool(bool value) noexcept -> JsonBuilder& {
        if (value) {
            buffer_.append("true", 4);
        } else {
            buffer_.append("false", 5);
        }
        needComma_ = true;
        return *this;
    }

    constexpr auto valueNull() noexcept -> JsonBuilder& {
        buffer_.append("null", 4);
        needComma_ = true;
        return *this;
    }

    constexpr auto arrayValueString(const char* value) noexcept -> JsonBuilder& {
        writeCommaIfNeeded();
        writeIndent();
        buffer_.append('"');
        buffer_.append(value);
        buffer_.append('"');
        needComma_ = true;
        return *this;
    }

    template<SizeType N>
    constexpr auto arrayValueString(const StaticString<N>& value) noexcept -> JsonBuilder& {
        writeCommaIfNeeded();
        writeIndent();
        buffer_.append('"');
        buffer_.append(value);
        buffer_.append('"');
        needComma_ = true;
        return *this;
    }

    template<SizeType N>
    constexpr auto keyValue(const char* name, const StaticString<N>& value) noexcept -> JsonBuilder& {
        key(name);
        return valueString(value);
    }

    constexpr auto keyValue(const char* name, const char* value) noexcept -> JsonBuilder& {
        key(name);
        return valueString(value);
    }

    constexpr auto keyValue(const char* name, BarcodeType value) noexcept -> JsonBuilder& {
        key(name);
        return valueInt(value);
    }

    constexpr auto keyValue(const char* name, bool value) noexcept -> JsonBuilder& {
        key(name);
        return valueBool(value);
    }
};

template<SizeType BufferSize = JSON_BUFFER_SIZE>
[[nodiscard]] constexpr auto buildResultsJson(const WorkChain& chain) noexcept -> JsonBuilder<BufferSize> {
    JsonBuilder<BufferSize> builder{};

    auto titleKey{formatBarcode(chain.titleBarcode)};

    builder.beginObject();
    builder.keyBeginObject(titleKey);

    builder.key("chain");
    builder.beginArray();

    for (const auto& sheet : chain.sheets) {
        auto barcodeStr{formatBarcode(sheet.barcode)};
        builder.arrayValueString(barcodeStr);
    }

    builder.endArray();

    builder.keyValue("sheet_count", static_cast<BarcodeType>(chain.sheetCount()));
    builder.keyValue("chain_valid", chain.chainValid);

    builder.endObject();
    builder.endObject();

    return builder;
}

} // namespace output_module::formatters
