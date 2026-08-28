cmake_minimum_required(VERSION 3.16)
project(ugts_gpu_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(UGTS_ANGLE_DIR "" CACHE PATH "Directory containing libEGL and libGLESv2; e.g. /usr/lib/chromium")

find_library(UGTS_EGL_LIBRARY NAMES EGL PATHS ${UGTS_ANGLE_DIR} NO_DEFAULT_PATH)
find_library(UGTS_GLES_LIBRARY NAMES GLESv2 PATHS ${UGTS_ANGLE_DIR} NO_DEFAULT_PATH)
if(NOT UGTS_EGL_LIBRARY)
  find_library(UGTS_EGL_LIBRARY NAMES EGL REQUIRED)
endif()
if(NOT UGTS_GLES_LIBRARY)
  find_library(UGTS_GLES_LIBRARY NAMES GLESv2 REQUIRED)
endif()

add_executable(ugts_bench src/ugts_bench.cpp)
target_include_directories(ugts_bench PRIVATE include)
target_link_libraries(ugts_bench PRIVATE ${UGTS_EGL_LIBRARY} ${UGTS_GLES_LIBRARY} dl)
if(UGTS_ANGLE_DIR)
  set_target_properties(ugts_bench PROPERTIES BUILD_RPATH "${UGTS_ANGLE_DIR}" INSTALL_RPATH "${UGTS_ANGLE_DIR}")
endif()

target_compile_options(ugts_bench PRIVATE -Wall -Wextra -Wpedantic)

find_library(UGTS_VULKAN_LIBRARY NAMES vulkan vulkan.so.1 libvulkan.so.1
  PATHS /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu ${UGTS_ANGLE_DIR})
if(NOT UGTS_VULKAN_LIBRARY)
  find_file(UGTS_VULKAN_LIBRARY NAMES libvulkan.so.1
    PATHS /lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu ${UGTS_ANGLE_DIR} REQUIRED)
endif()
add_executable(ugts_vulkan_bench src/ugts_vulkan_bench.cpp)
target_include_directories(ugts_vulkan_bench PRIVATE include)
target_link_libraries(ugts_vulkan_bench PRIVATE ${UGTS_VULKAN_LIBRARY} dl)
target_compile_options(ugts_vulkan_bench PRIVATE -Wall -Wextra -Wpedantic)
