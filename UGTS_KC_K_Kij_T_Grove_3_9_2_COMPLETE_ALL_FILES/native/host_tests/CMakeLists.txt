cmake_minimum_required(VERSION 3.22)
project(ugts_kc_host_touch_tests LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(
    UGTS_ANDROID_CPP_DIR
    "${CMAKE_CURRENT_LIST_DIR}/../../src/ugts_kc3/android_template/project/app/src/main/cpp"
    CACHE PATH "Packaged Android C++ source directory"
)

add_executable(
    touch_router_tests
    touch_router_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/touch_router.cpp"
)
target_include_directories(touch_router_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    graph_vm_tests
    graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
)
target_include_directories(graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

if(MSVC)
    target_compile_options(touch_router_tests PRIVATE /W4 /permissive-)
    target_compile_options(graph_vm_tests PRIVATE /W4 /permissive-)
else()
    target_compile_options(touch_router_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
endif()
