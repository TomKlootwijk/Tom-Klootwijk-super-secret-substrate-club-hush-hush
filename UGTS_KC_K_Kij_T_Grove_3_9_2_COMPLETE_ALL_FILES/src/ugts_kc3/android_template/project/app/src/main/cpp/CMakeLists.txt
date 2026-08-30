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
option(UGTS_KC_GSP4_SEED_CAMERA "Build exact Camera2 -> UGYUVS1 seed capture runtime" OFF)

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

# The SHA-1 build ID is calculated before Android strips packaged libraries.
# Normalize only DWARF paths so independent short workspaces produce the same
# ID while keeping full debug information for crash symbolization.
set(UGTS_KC_DEBUG_PATH_OPTIONS
    "-fdebug-prefix-map=${CMAKE_CURRENT_SOURCE_DIR}=/ugts-kc/source"
    "-fdebug-prefix-map=${CMAKE_CURRENT_BINARY_DIR}=/ugts-kc/build"
)
target_compile_options(native_app_glue PRIVATE
    ${UGTS_KC_DEBUG_PATH_OPTIONS}
)

set(UGTS_KC_NATIVE_SOURCES
    main.cpp
    engine.cpp
    chrono_video_lut.cpp
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

if(UGTS_KC_GSP4_SEED_CAMERA)
    set(UGTS_KC_UGYUVS1_DIR "${CMAKE_CURRENT_SOURCE_DIR}/ugtc4d" CACHE PATH
        "Directory containing the portable UGYUVS1 sources copied by the exporter")
    foreach(UGTS_KC_UGYUVS1_FILE
            ugtc4d_decoder.hpp ugtc4d_decoder.cpp
            seeded_uglut2_traversal.hpp seeded_uglut2_traversal.cpp
            full_substrate_camera.hpp full_substrate_camera.cpp
            yuv_seed_capture.hpp yuv_seed_capture.cpp)
        if(NOT EXISTS "${UGTS_KC_UGYUVS1_DIR}/${UGTS_KC_UGYUVS1_FILE}")
            message(FATAL_ERROR
                "GSP4 seed flavor requires ${UGTS_KC_UGYUVS1_DIR}/${UGTS_KC_UGYUVS1_FILE}")
        endif()
        file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/ugyuvs1")
        configure_file(
            "${UGTS_KC_UGYUVS1_DIR}/${UGTS_KC_UGYUVS1_FILE}"
            "${CMAKE_CURRENT_BINARY_DIR}/ugyuvs1/${UGTS_KC_UGYUVS1_FILE}"
            COPYONLY
        )
    endforeach()
    list(APPEND UGTS_KC_NATIVE_SOURCES
        chrono_capture_sha256.cpp
        chrono_scene_binding.cpp
        chrono_capture_queue.cpp
        chrono_camera_recorder.cpp
        chrono_vulkan_residual.cpp
        chrono_seed_capture_session.cpp
        "${CMAKE_CURRENT_BINARY_DIR}/ugyuvs1/ugtc4d_decoder.cpp"
        "${CMAKE_CURRENT_BINARY_DIR}/ugyuvs1/seeded_uglut2_traversal.cpp"
        "${CMAKE_CURRENT_BINARY_DIR}/ugyuvs1/full_substrate_camera.cpp"
        "${CMAKE_CURRENT_BINARY_DIR}/ugyuvs1/yuv_seed_capture.cpp"
    )
else()
    list(APPEND UGTS_KC_NATIVE_SOURCES
        chrono_mp4_transport.cpp
        chrono_video_timeline.cpp
        chrono_video_player.cpp
    )
endif()

add_library(ugts_kc_native SHARED ${UGTS_KC_NATIVE_SOURCES})

target_include_directories(ugts_kc_native PRIVATE
    "${CMAKE_CURRENT_BINARY_DIR}"
)
if(UGTS_KC_GSP4_SEED_CAMERA)
    target_include_directories(ugts_kc_native PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/ugyuvs1")
endif()

target_compile_definitions(ugts_kc_native PRIVATE
    UGTS_KC_PROFILE_HINT="${UGTS_KC_PROFILE_HINT}"
    UGTS_KC_GSP4_SEED_CAMERA=$<BOOL:${UGTS_KC_GSP4_SEED_CAMERA}>
)

target_compile_options(ugts_kc_native PRIVATE
    -Wall -Wextra -Wpedantic
    ${UGTS_KC_DEBUG_PATH_OPTIONS}
)
if(UGTS_KC_GSP4_SEED_CAMERA)
    # The physical debug APK retains symbols but must sustain the authoritative
    # 720p/30 capture spool and complete post-capture exact replay in practical
    # time. Optimization does not alter the integer/file ABI.
    target_compile_options(ugts_kc_native PRIVATE "$<$<CONFIG:Debug>:-O2>")
endif()

target_link_options(ugts_kc_native PRIVATE
    "-Wl,--build-id=sha1"
)

target_link_libraries(ugts_kc_native
    native_app_glue
    android
    log
    EGL
    GLESv3
    dl
)
if(UGTS_KC_GSP4_SEED_CAMERA)
    # libmediandk is AImageReader capture plumbing only. The seed flavor has
    # no AMediaCodec/AMediaExtractor source or symbol; Vulkan performs the
    # integer UGCAMNODE-FX1 profile-2 operator/residual on the physical GPU.
    target_link_libraries(ugts_kc_native camera2ndk mediandk vulkan)
else()
    target_link_libraries(ugts_kc_native mediandk)
endif()
