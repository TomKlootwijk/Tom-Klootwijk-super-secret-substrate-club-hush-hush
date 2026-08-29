cmake_minimum_required(VERSION 3.24)
project(ugts_go19 LANGUAGES CXX)

option(UGTS_ENABLE_CUDA "Build optional CUDA accelerator scaffolding" OFF)

add_library(ugts_go_core STATIC
  src/go_state.cpp
  src/persistent_state.cpp
  src/pndag.cpp
  src/pndag_checkpoint.cpp
  src/sha256.cpp)
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

add_executable(ugts_go_pndag src/pndag_cli.cpp)
target_link_libraries(ugts_go_pndag PRIVATE ugts_go_core)

include(CTest)
if(BUILD_TESTING)
  add_test(NAME ugts_go19_smoke COMMAND ugts_go19_smoke)

  add_executable(ugts_go_core_tests tests/go_state_test.cpp)
  target_link_libraries(ugts_go_core_tests PRIVATE ugts_go_core)
  add_test(NAME ugts_go_core_tests COMMAND ugts_go_core_tests)

  add_executable(ugts_go_persistent_state_tests
                 tests/persistent_state_test.cpp)
  target_link_libraries(ugts_go_persistent_state_tests PRIVATE ugts_go_core)
  add_test(NAME ugts_go_persistent_state_tests
           COMMAND ugts_go_persistent_state_tests)

  add_executable(ugts_go_pndag_tests tests/pndag_test.cpp)
  target_link_libraries(ugts_go_pndag_tests PRIVATE ugts_go_core)
  add_test(NAME ugts_go_pndag_tests COMMAND ugts_go_pndag_tests)

  add_executable(ugts_go_pndag_checkpoint_tests
                 tests/pndag_checkpoint_test.cpp)
  target_link_libraries(ugts_go_pndag_checkpoint_tests PRIVATE ugts_go_core)
  add_test(NAME ugts_go_pndag_checkpoint_tests
           COMMAND ugts_go_pndag_checkpoint_tests)

  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_test(
    NAME ugts_go_python_cpp_parity
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/python_cpp_parity.py
            --evaluator $<TARGET_FILE:ugts_go_trace_eval>)
  set_tests_properties(
    ugts_go_python_cpp_parity
    PROPERTIES
      TIMEOUT 60)

  add_test(
    NAME ugts_go_pndag_cli_tests
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/pndag_cli_test.py
            --cli $<TARGET_FILE:ugts_go_pndag>)
  set_tests_properties(ugts_go_pndag_cli_tests PROPERTIES TIMEOUT 60)

  add_test(
    NAME ugts_go_pndag_checkpoint_cli_tests
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/pndag_checkpoint_cli_test.py
            --cli $<TARGET_FILE:ugts_go_pndag>)
  set_tests_properties(ugts_go_pndag_checkpoint_cli_tests PROPERTIES TIMEOUT 180)
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
  add_library(ugts_go_cuda STATIC
    cuda/packed_kernels.cu
    cuda/cuda_verified_expander.cu)
  target_include_directories(ugts_go_cuda PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/cuda)
  target_link_libraries(ugts_go_cuda PUBLIC ugts_go_core)
  target_compile_features(ugts_go_cuda PUBLIC cuda_std_17)
  set_target_properties(ugts_go_cuda PROPERTIES CUDA_SEPARABLE_COMPILATION ON)

  add_executable(ugts_go19_gpu_probe cuda/gpu_probe.cu)
  target_compile_features(ugts_go19_gpu_probe PRIVATE cuda_std_17)

  if(BUILD_TESTING)
    add_executable(ugts_go_cuda_empty_mask_eval tests/cuda_empty_mask_eval.cu)
    target_link_libraries(ugts_go_cuda_empty_mask_eval PRIVATE ugts_go_cuda)
    target_compile_features(ugts_go_cuda_empty_mask_eval PRIVATE cuda_std_17)
    set_target_properties(
      ugts_go_cuda_empty_mask_eval
      PROPERTIES CUDA_SEPARABLE_COMPILATION ON)
    add_test(
      NAME ugts_go_cuda_empty_mask_parity
      COMMAND ${Python3_EXECUTABLE}
              ${CMAKE_CURRENT_SOURCE_DIR}/tests/cuda_empty_mask_parity.py
              --evaluator $<TARGET_FILE:ugts_go_cuda_empty_mask_eval>)
    set_tests_properties(
      ugts_go_cuda_empty_mask_parity
      PROPERTIES
        TIMEOUT 300)

    add_executable(ugts_go_cuda_local_transition_eval
                   tests/cuda_local_transition_eval.cu)
    target_link_libraries(ugts_go_cuda_local_transition_eval
                          PRIVATE ugts_go_cuda)
    target_compile_features(ugts_go_cuda_local_transition_eval
                            PRIVATE cuda_std_17)
    set_target_properties(
      ugts_go_cuda_local_transition_eval
      PROPERTIES CUDA_SEPARABLE_COMPILATION ON)

    add_executable(ugts_go_cuda_local_transition_guards
                   tests/cuda_local_transition_guards.cu)
    target_link_libraries(ugts_go_cuda_local_transition_guards
                          PRIVATE ugts_go_cuda)
    target_compile_features(ugts_go_cuda_local_transition_guards
                            PRIVATE cuda_std_17)
    set_target_properties(
      ugts_go_cuda_local_transition_guards
      PROPERTIES CUDA_SEPARABLE_COMPILATION ON)

    add_executable(ugts_go_cuda_local_transition_scale
                   tests/cuda_local_transition_scale.cu)
    target_link_libraries(ugts_go_cuda_local_transition_scale
                          PRIVATE ugts_go_cuda)
    target_compile_features(ugts_go_cuda_local_transition_scale
                            PRIVATE cuda_std_17)
    set_target_properties(
      ugts_go_cuda_local_transition_scale
      PROPERTIES CUDA_SEPARABLE_COMPILATION ON)

    add_test(
      NAME ugts_go_cuda_local_transition_parity
      COMMAND ${Python3_EXECUTABLE}
              ${CMAKE_CURRENT_SOURCE_DIR}/tests/cuda_local_transition_parity.py
              --evaluator $<TARGET_FILE:ugts_go_cuda_local_transition_eval>
              --guard-evaluator
              $<TARGET_FILE:ugts_go_cuda_local_transition_guards>)
    set_tests_properties(
      ugts_go_cuda_local_transition_parity
      PROPERTIES
        TIMEOUT 300)

    add_test(
      NAME ugts_go_cuda_local_transition_guards
      COMMAND $<TARGET_FILE:ugts_go_cuda_local_transition_guards>)
    set_tests_properties(
      ugts_go_cuda_local_transition_guards
      PROPERTIES
        TIMEOUT 300)

    # Structural coverage runs the complete deterministic corpus through both
    # stream modes. The explicit 10m campaign remains an operator command so a
    # normal CTest invocation cannot accidentally spend campaign-scale time.
    add_test(
      NAME ugts_go_cuda_local_transition_scale_structural
      COMMAND $<TARGET_FILE:ugts_go_cuda_local_transition_scale>
              --target-unique-corpus-slots 50000
              --batch-states 8
              --seed 88442398638062)
    set_tests_properties(
      ugts_go_cuda_local_transition_scale_structural
      PROPERTIES
        TIMEOUT 900)
  endif()
endif()
