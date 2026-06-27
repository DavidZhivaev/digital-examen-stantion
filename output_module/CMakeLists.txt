cmake_minimum_required(VERSION 3.20)
project(output_module VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -Wextra -Wpedantic -Werror")
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0 -fsanitize=address,undefined")
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -mtune=native -flto")

set(OUTPUT_MODULE_HEADERS
    include/core/types.hpp
    include/core/static_string.hpp
    include/core/static_vector.hpp
    include/core/file_handle.hpp
    include/core/memory_buffer.hpp
    include/core/sheet_data.hpp
    include/core/uuid_generator.hpp
    include/formatters/json_builder.hpp
    include/generators/pdf_primitives.hpp
    include/generators/pdf_generator.hpp
    include/generators/zip_primitives.hpp
    include/generators/zip_packager.hpp
    include/output_generator.hpp
)

add_library(output_module_headers INTERFACE)
target_include_directories(output_module_headers INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

add_executable(output_generator_cli
    src/main.cpp
)

target_link_libraries(output_generator_cli PRIVATE
    output_module_headers
)

target_compile_options(output_generator_cli PRIVATE
    -fno-rtti
    -fno-exceptions
)

find_package(Python3 COMPONENTS Interpreter Development)
find_package(pybind11 QUIET)

if(Python3_FOUND AND pybind11_FOUND)
    pybind11_add_module(output_generator_cpp
        src/python_bindings.cpp
    )

    target_link_libraries(output_generator_cpp PRIVATE
        output_module_headers
    )

    target_compile_options(output_generator_cpp PRIVATE
        -fno-rtti
    )

    install(TARGETS output_generator_cpp
        LIBRARY DESTINATION ${Python3_SITELIB}
    )
endif()

install(TARGETS output_generator_cli
    RUNTIME DESTINATION bin
)

install(DIRECTORY include/
    DESTINATION include/output_module
    FILES_MATCHING PATTERN "*.hpp"
)

enable_testing()

add_executable(test_static_string
    tests/test_static_string.cpp
)
target_link_libraries(test_static_string PRIVATE output_module_headers)

add_executable(test_json_builder
    tests/test_json_builder.cpp
)
target_link_libraries(test_json_builder PRIVATE output_module_headers)

add_test(NAME StaticStringTest COMMAND test_static_string)
add_test(NAME JsonBuilderTest COMMAND test_json_builder)
