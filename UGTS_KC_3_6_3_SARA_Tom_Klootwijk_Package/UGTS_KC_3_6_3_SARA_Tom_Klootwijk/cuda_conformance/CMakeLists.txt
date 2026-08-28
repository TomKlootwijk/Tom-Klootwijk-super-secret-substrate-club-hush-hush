cmake_minimum_required(VERSION 3.24)

project(sara363_cuda_conformance VERSION 0.1.0 LANGUAGES CXX CUDA)

set(SARA_CUDA_ARCH "120" CACHE STRING "CUDA architecture to compile for")

add_executable(sara363_cuda_conformance src/main.cu)
target_include_directories(sara363_cuda_conformance PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_compile_features(sara363_cuda_conformance PRIVATE cxx_std_20)
set_target_properties(sara363_cuda_conformance PROPERTIES
    CUDA_STANDARD 20
    CUDA_STANDARD_REQUIRED YES
    CXX_STANDARD 20
    CXX_STANDARD_REQUIRED YES
    CUDA_RUNTIME_LIBRARY Shared
    CUDA_ARCHITECTURES "${SARA_CUDA_ARCH}-real;${SARA_CUDA_ARCH}-virtual"
)

target_compile_options(sara363_cuda_conformance PRIVATE
    $<$<COMPILE_LANGUAGE:CUDA>:--generate-line-info;-Xptxas=-v>
    $<$<COMPILE_LANGUAGE:CXX>:/W4>
)

include(CTest)
if(BUILD_TESTING)
    add_test(NAME fixed_vector_quick
             COMMAND sara363_cuda_conformance --quick --no-json)
endif()
