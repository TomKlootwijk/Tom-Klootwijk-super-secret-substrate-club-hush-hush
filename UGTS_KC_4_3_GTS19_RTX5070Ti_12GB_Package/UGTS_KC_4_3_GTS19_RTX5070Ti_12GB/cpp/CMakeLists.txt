cmake_minimum_required(VERSION 3.23)
project(ugts_go19 LANGUAGES CXX)

option(UGTS_ENABLE_CUDA "Build optional CUDA accelerator scaffolding" OFF)

add_library(ugts_go_core STATIC src/go_state.cpp)
target_include_directories(ugts_go_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_features(ugts_go_core PUBLIC cxx_std_17)
if(MSVC)
  target_compile_options(ugts_go_core PRIVATE /W4 /permissive-)
else()
  target_compile_options(ugts_go_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
endif()

add_executable(ugts_go19_smoke src/main.cpp)
target_link_libraries(ugts_go19_smoke PRIVATE ugts_go_core)

add_executable(ugts_go_trace_eval src/trace_eval.cpp)
target_link_libraries(ugts_go_trace_eval PRIVATE ugts_go_core)

include(CTest)
if(BUILD_TESTING)
  add_test(NAME ugts_go19_smoke COMMAND ugts_go19_smoke)

  add_executable(ugts_go_core_tests tests/go_state_test.cpp)
  target_link_libraries(ugts_go_core_tests PRIVATE ugts_go_core)
  add_test(NAME ugts_go_core_tests COMMAND ugts_go_core_tests)

  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_test(
    NAME ugts_go_python_cpp_parity
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/python_cpp_parity.py
            --evaluator $<TARGET_FILE:ugts_go_trace_eval>)
  set_tests_properties(
    ugts_go_python_cpp_parity
    PROPERTIES
      TIMEOUT 60
      PASS_REGULAR_EXPRESSION "\"mismatches\":0")
endif()

if(UGTS_ENABLE_CUDA)
  include(CheckLanguage)
  check_language(CUDA)
  if(NOT CMAKE_CUDA_COMPILER)
    message(FATAL_ERROR "UGTS_ENABLE_CUDA=ON but no CUDA compiler was found")
  endif()
  enable_language(CUDA)
  if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
    set(CMAKE_CUDA_ARCHITECTURES native)
  endif()
  add_library(ugts_go_cuda STATIC cuda/packed_kernels.cu)
  target_include_directories(ugts_go_cuda PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/cuda)
  target_compile_features(ugts_go_cuda PUBLIC cuda_std_17)
  set_target_properties(ugts_go_cuda PROPERTIES CUDA_SEPARABLE_COMPILATION ON)

  add_executable(ugts_go19_gpu_probe cuda/gpu_probe.cu)
  target_compile_features(ugts_go19_gpu_probe PRIVATE cuda_std_17)
endif()
