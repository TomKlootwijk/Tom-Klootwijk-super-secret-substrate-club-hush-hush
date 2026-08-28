cmake_minimum_required(VERSION 3.24)

project(klb_cuda_arch_test VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(KLB_BUILD_CUDA "Build the CUDA benchmark when a CUDA compiler is available" ON)
option(KLB_REQUIRE_CUDA "Fail configuration if CUDA is unavailable" OFF)
option(KLB_FAST_MATH "Use CUDA fast math (changes numerical tolerances)" OFF)
set(KLB_CUDA_ARCH "120" CACHE STRING "CUDA architecture number; RTX 50 consumer Blackwell is 120")

add_library(klb_core STATIC
    src/format.cpp
    src/ply.cpp
)
target_include_directories(klb_core PUBLIC include)
target_compile_features(klb_core PUBLIC cxx_std_20)

if(MSVC)
    target_compile_options(klb_core PRIVATE /W4 /permissive-)
else()
    target_compile_options(klb_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
endif()

add_executable(klb_pack src/pack_main.cpp)
target_link_libraries(klb_pack PRIVATE klb_core)

include(CTest)
if(BUILD_TESTING)
    add_executable(klb_tests tests/test_cpu.cpp)
    target_link_libraries(klb_tests PRIVATE klb_core)
    add_test(NAME klb_cpu_tests COMMAND klb_tests)
endif()

if(KLB_BUILD_CUDA)
    include(CheckLanguage)
    check_language(CUDA)
    if(CMAKE_CUDA_COMPILER)
        enable_language(CUDA)
        if(CMAKE_CUDA_COMPILER_VERSION VERSION_LESS 12.8)
            message(FATAL_ERROR "CUDA 12.8 or newer is required for native sm_120 compilation")
        endif()

        add_executable(klb_bench src/bench.cu)
        target_link_libraries(klb_bench PRIVATE klb_core)
        target_include_directories(klb_bench PRIVATE include)
        set_target_properties(klb_bench PROPERTIES
            CUDA_STANDARD 20
            CUDA_STANDARD_REQUIRED ON
            CUDA_EXTENSIONS OFF
            CUDA_ARCHITECTURES "${KLB_CUDA_ARCH}-real;${KLB_CUDA_ARCH}-virtual"
        )
        target_compile_options(klb_bench PRIVATE
            $<$<COMPILE_LANGUAGE:CUDA>:--generate-line-info>
            $<$<COMPILE_LANGUAGE:CUDA>:-Xptxas=-v>
        )
        if(KLB_FAST_MATH)
            target_compile_options(klb_bench PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:--use_fast_math>)
        endif()
        if(MSVC)
            target_compile_options(klb_bench PRIVATE $<$<COMPILE_LANGUAGE:CXX>:/W4>)
        else()
            target_compile_options(klb_bench PRIVATE $<$<COMPILE_LANGUAGE:CXX>:-Wall;-Wextra;-Wpedantic>)
        endif()
    elseif(KLB_REQUIRE_CUDA)
        message(FATAL_ERROR "KLB_REQUIRE_CUDA is ON, but no CUDA compiler was found")
    else()
        message(WARNING "CUDA compiler not found: building klb_pack and CPU tests only")
    endif()
endif()
