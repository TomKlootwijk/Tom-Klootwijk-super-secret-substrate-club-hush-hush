cmake_minimum_required(VERSION 3.20)
project(ugts41_host LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
find_package(ZLIB REQUIRED)
set(CORE "${CMAKE_CURRENT_LIST_DIR}/../../android_project/app/src/main/cpp/core")
set(CORE_SOURCES
 ${CORE}/seed.cpp ${CORE}/varint.cpp ${CORE}/crc32.cpp ${CORE}/sha256.cpp
 ${CORE}/spatial_keys.cpp ${CORE}/feature_extractor.cpp ${CORE}/verifier.cpp
 ${CORE}/ledger.cpp ${CORE}/pipeline.cpp ${CORE}/kseed_codec.cpp)
add_executable(ugts41_host_tests host_tests.cpp ${CORE_SOURCES})
target_include_directories(ugts41_host_tests PRIVATE ${CORE})
target_link_libraries(ugts41_host_tests PRIVATE ZLIB::ZLIB)
target_compile_options(ugts41_host_tests PRIVATE -Wall -Wextra -Wpedantic)
add_executable(ugts41_demo_builder demo_builder.cpp ${CORE_SOURCES})
target_include_directories(ugts41_demo_builder PRIVATE ${CORE})
target_link_libraries(ugts41_demo_builder PRIVATE ZLIB::ZLIB)
target_compile_options(ugts41_demo_builder PRIVATE -Wall -Wextra -Wpedantic)
