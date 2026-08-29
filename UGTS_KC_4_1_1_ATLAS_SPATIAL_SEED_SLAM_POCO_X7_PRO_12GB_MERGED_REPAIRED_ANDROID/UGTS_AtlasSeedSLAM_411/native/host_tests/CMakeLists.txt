cmake_minimum_required(VERSION 3.16)
project(ugts_seed_host_tests LANGUAGES CXX)
add_executable(ugts_seed_host_tests
    test_seed_core.cpp
    ../core/seed_core.cpp)
target_include_directories(ugts_seed_host_tests PRIVATE ../core)
target_compile_features(ugts_seed_host_tests PRIVATE cxx_std_20)
target_compile_options(ugts_seed_host_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
