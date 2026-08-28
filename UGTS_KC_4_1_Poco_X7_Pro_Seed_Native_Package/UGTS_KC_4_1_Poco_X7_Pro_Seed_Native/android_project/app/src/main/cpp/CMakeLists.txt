cmake_minimum_required(VERSION 3.22.1)
project(ugts_kc_41_spatial LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)

add_library(ugts_kc_41_spatial SHARED
    ${ANDROID_NDK}/sources/android/native_app_glue/android_native_app_glue.c
    main.cpp engine.cpp camera_ndk.cpp imu_ndk.cpp permissions.cpp
    thermal_policy.cpp device_profile.cpp renderer_bayer.cpp storage_android.cpp
    core/seed.cpp core/varint.cpp core/crc32.cpp core/sha256.cpp core/spatial_keys.cpp
    core/feature_extractor.cpp core/verifier.cpp core/ledger.cpp core/pipeline.cpp
    core/kseed_codec.cpp)

target_include_directories(ugts_kc_41_spatial PRIVATE
    ${ANDROID_NDK}/sources/android/native_app_glue
    ${CMAKE_CURRENT_SOURCE_DIR})

target_compile_definitions(ugts_kc_41_spatial PRIVATE
    UGTS41_PROFILE_HINT="${UGTS41_PROFILE_HINT}")

target_compile_options(ugts_kc_41_spatial PRIVATE
    -fno-rtti
    -ffunction-sections
    -fdata-sections
    $<$<CONFIG:Release>:-O3>)

# The portable storage reader uses exceptions for bounded decode errors. Re-enable
# them for the native target; this preserves defensive error propagation.
target_compile_options(ugts_kc_41_spatial PRIVATE -fexceptions)

target_link_options(ugts_kc_41_spatial PRIVATE
    -Wl,--gc-sections
    -Wl,--build-id=sha1)

target_link_libraries(ugts_kc_41_spatial
    android log EGL GLESv3 camera2ndk mediandk z dl)
