cmake_minimum_required(VERSION 3.24)
project(ugts_chess2_native VERSION 2.0.0 LANGUAGES CXX)

option(UGTS_ENABLE_CUDA "Build optional CUDA candidate and retrograde backends" ON)
set(UGTS_CUDA_ARCH "120" CACHE STRING "CUDA architecture; GeForce RTX 50-series laptop target is SM120")

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

function(ugts_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive-)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endfunction()

# Independent C++20 exact legal kernel, heuristic search, SHA-256 and abstract
# finite-graph retrograde solver.
add_library(ugts_chess2_core STATIC
    src/core.cpp
    src/search.cpp
    src/sha256.cpp
    src/retrograde_cpu.cpp
)
target_include_directories(ugts_chess2_core PUBLIC include)
target_compile_definitions(ugts_chess2_core PUBLIC UGTS_CHESS2_VERSION="${PROJECT_VERSION}")
ugts_warnings(ugts_chess2_core)

# 64-byte packed position protocol used by Python <-> C++/CUDA candidate
# expansion.  Its output is proposal-only and is independently verified.
add_library(ugts_chess_packed STATIC src/fen.cpp)
target_include_directories(ugts_chess_packed PUBLIC include)
ugts_warnings(ugts_chess_packed)

include(CheckLanguage)
set(UGTS_CUDA_ACTIVE OFF)
if(UGTS_ENABLE_CUDA)
    check_language(CUDA)
    if(NOT CMAKE_CUDA_COMPILER)
        message(FATAL_ERROR
            "UGTS_ENABLE_CUDA=ON, but no working CUDA compiler was found. "
            "The CUDA release must not silently fall back to the CPU stubs.")
    endif()
    enable_language(CUDA)
    set(CMAKE_CUDA_STANDARD 17)
    set(CMAKE_CUDA_STANDARD_REQUIRED ON)
    if(NOT CMAKE_CUDA_ARCHITECTURES)
        set(CMAKE_CUDA_ARCHITECTURES "${UGTS_CUDA_ARCH}")
    endif()
    find_package(CUDAToolkit REQUIRED)

    add_library(ugts_chess2_retro_backend STATIC cuda/retrograde_cuda.cu)
    target_include_directories(ugts_chess2_retro_backend PUBLIC include)
    target_link_libraries(ugts_chess2_retro_backend PUBLIC ugts_chess2_core CUDA::cudart)
    set_target_properties(ugts_chess2_retro_backend PROPERTIES CUDA_SEPARABLE_COMPILATION ON POSITION_INDEPENDENT_CODE ON)

    add_library(ugts_chess_cuda_backend STATIC cuda/cuda_api.cu)
    target_include_directories(ugts_chess_cuda_backend PUBLIC include)
    target_link_libraries(ugts_chess_cuda_backend PUBLIC ugts_chess_packed CUDA::cudart)
    set_target_properties(ugts_chess_cuda_backend PROPERTIES CUDA_SEPARABLE_COMPILATION ON POSITION_INDEPENDENT_CODE ON)
    set(UGTS_CUDA_ACTIVE ON)
endif()

if(NOT UGTS_CUDA_ACTIVE)
    add_library(ugts_chess2_retro_backend STATIC src/cuda_stub.cpp)
    target_include_directories(ugts_chess2_retro_backend PUBLIC include)
    target_link_libraries(ugts_chess2_retro_backend PUBLIC ugts_chess2_core)

    add_library(ugts_chess_cuda_backend STATIC src/cuda_api_stub.cpp)
    target_include_directories(ugts_chess_cuda_backend PUBLIC include)
    target_link_libraries(ugts_chess_cuda_backend PUBLIC ugts_chess_packed)
endif()

add_executable(ugts-chess2 src/main.cpp)
target_link_libraries(ugts-chess2 PRIVATE ugts_chess2_retro_backend ugts_chess2_core)
ugts_warnings(ugts-chess2)

add_executable(ugts-chess-gpu src/gpu_main.cpp)
target_link_libraries(ugts-chess-gpu PRIVATE ugts_chess_cuda_backend ugts_chess_packed)
ugts_warnings(ugts-chess-gpu)

include(CTest)
if(BUILD_TESTING)
    add_executable(ugts_chess2_tests tests/native_tests.cpp)
    target_link_libraries(ugts_chess2_tests PRIVATE ugts_chess2_retro_backend ugts_chess2_core)
    ugts_warnings(ugts_chess2_tests)
    add_test(NAME ugts_chess2_native_tests COMMAND ugts_chess2_tests)
    add_test(NAME ugts_chess2_cli_selftest COMMAND ugts-chess2 selftest)
    add_test(NAME ugts_chess_gpu_selftest COMMAND ugts-chess-gpu self-test)
endif()

install(TARGETS ugts-chess2 ugts-chess-gpu RUNTIME DESTINATION bin)
