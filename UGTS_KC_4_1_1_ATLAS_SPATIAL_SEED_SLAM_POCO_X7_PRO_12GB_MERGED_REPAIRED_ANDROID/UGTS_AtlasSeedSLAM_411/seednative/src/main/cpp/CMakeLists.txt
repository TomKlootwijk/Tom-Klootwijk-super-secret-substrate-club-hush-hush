cmake_minimum_required(VERSION 3.22.1)
project(ugts_seed_native LANGUAGES CXX)

add_library(ugts_seed_native SHARED
    jni_bridge.cpp
    ../../../../native/core/seed_core.cpp)

target_include_directories(ugts_seed_native PRIVATE
    ../../../../native/core)

target_compile_features(ugts_seed_native PRIVATE cxx_std_20)
target_compile_options(ugts_seed_native PRIVATE
    -Os -ffunction-sections -fdata-sections -fvisibility=hidden)
target_link_options(ugts_seed_native PRIVATE
    -Wl,--gc-sections -Wl,--strip-all)
find_library(log-lib log)
target_link_libraries(ugts_seed_native PRIVATE ${log-lib})
