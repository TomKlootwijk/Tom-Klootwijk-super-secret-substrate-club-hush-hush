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
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
)
target_include_directories(graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    nearest_tag_graph_vm_tests
    nearest_tag_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
)
target_include_directories(nearest_tag_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    nearest_in_cone_graph_vm_tests
    nearest_in_cone_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
)
target_include_directories(nearest_in_cone_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    timer_graph_vm_tests
    timer_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
)
target_include_directories(timer_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    trigger_area_tests
    trigger_area_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/trigger_area.cpp"
)
target_include_directories(trigger_area_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    scatter_population_tests
    scatter_population_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
)
target_include_directories(scatter_population_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

if(MSVC)
    target_compile_options(touch_router_tests PRIVATE /W4 /permissive-)
    target_compile_options(graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(nearest_tag_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(nearest_in_cone_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(timer_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(trigger_area_tests PRIVATE /W4 /permissive-)
    target_compile_options(scatter_population_tests PRIVATE /W4 /permissive-)
else()
    target_compile_options(touch_router_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(nearest_tag_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(nearest_in_cone_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(timer_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(trigger_area_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(scatter_population_tests PRIVATE -Wall -Wextra -Wpedantic)
endif()
