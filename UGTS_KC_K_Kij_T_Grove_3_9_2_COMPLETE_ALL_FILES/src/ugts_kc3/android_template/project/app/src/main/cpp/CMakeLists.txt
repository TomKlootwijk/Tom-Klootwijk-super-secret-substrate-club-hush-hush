cmake_minimum_required(VERSION 3.22.1)
project(ugts_kc_native LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT DEFINED UGTS_KC_PROFILE_HINT)
    set(UGTS_KC_PROFILE_HINT "auto")
endif()

add_library(native_app_glue STATIC
    ${ANDROID_NDK}/sources/android/native_app_glue/android_native_app_glue.c
)
target_include_directories(native_app_glue PUBLIC
    ${ANDROID_NDK}/sources/android/native_app_glue
)

add_library(ugts_kc_native SHARED
    main.cpp
    engine.cpp
    renderer_gles3.cpp
    scene_pack.cpp
    device_profile.cpp
    adaptive_quality.cpp
)

target_include_directories(ugts_kc_native PRIVATE
    ${ANDROID_NDK}/sources/android/native_app_glue
)

target_compile_definitions(ugts_kc_native PRIVATE
    UGTS_KC_PROFILE_HINT="${UGTS_KC_PROFILE_HINT}"
)

target_compile_options(ugts_kc_native PRIVATE
    -Wall -Wextra -Wpedantic
)

target_link_libraries(ugts_kc_native
    native_app_glue
    android
    log
    EGL
    GLESv3
    dl
)
