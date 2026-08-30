cmake_minimum_required(VERSION 3.22.1)
project(ugts_kc_native LANGUAGES C CXX)

# Generated projects can live below very long learner/workspace paths on
# Windows.  Force CMake to hash long object subpaths before Ninja hits the
# legacy directory-length boundary (notably for NDK native_app_glue sources).
set(CMAKE_OBJECT_PATH_MAX 160)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT DEFINED UGTS_KC_PROFILE_HINT)
    set(UGTS_KC_PROFILE_HINT "auto")
endif()

# CMake otherwise mirrors the NDK's absolute source path below
# CMakeFiles/native_app_glue.dir.  On Windows that can exceed Ninja's legacy
# directory limit when a learner keeps a project in a long-named workspace.
# Copy the tiny NDK glue sources into the build directory first so every
# generated object path stays local and short.
configure_file(
    "${ANDROID_NDK}/sources/android/native_app_glue/android_native_app_glue.c"
    "${CMAKE_CURRENT_BINARY_DIR}/android_native_app_glue.c"
    COPYONLY
)
configure_file(
    "${ANDROID_NDK}/sources/android/native_app_glue/android_native_app_glue.h"
    "${CMAKE_CURRENT_BINARY_DIR}/android_native_app_glue.h"
    COPYONLY
)

add_library(native_app_glue STATIC
    "${CMAKE_CURRENT_BINARY_DIR}/android_native_app_glue.c"
)
target_include_directories(native_app_glue PUBLIC
    "${CMAKE_CURRENT_BINARY_DIR}"
)

add_library(ugts_kc_native SHARED
    main.cpp
    engine.cpp
    body_physics.cpp
    touch_router.cpp
    trigger_area.cpp
    graph_vm.cpp
    polar_kinematics.cpp
    polar_populations.cpp
    gpu_timer_query.cpp
    render_substrate.cpp
    transform_animation.cpp
    transform_hierarchy.cpp
    renderer_gles3.cpp
    scene_pack.cpp
    device_profile.cpp
    adaptive_quality.cpp
    grove_juice.cpp
    grove_tuning.cpp
    scatter_population.cpp
)

target_include_directories(ugts_kc_native PRIVATE
    "${CMAKE_CURRENT_BINARY_DIR}"
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
