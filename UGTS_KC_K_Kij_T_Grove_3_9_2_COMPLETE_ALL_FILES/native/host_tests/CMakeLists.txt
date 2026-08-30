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
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    nearest_tag_graph_vm_tests
    nearest_tag_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(nearest_tag_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    nearest_in_cone_graph_vm_tests
    nearest_in_cone_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(nearest_in_cone_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    timer_graph_vm_tests
    timer_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(timer_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    message_graph_vm_tests
    message_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(message_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

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

add_executable(
    transform_animation_tests
    transform_animation_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(transform_animation_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    animation_graph_vm_tests
    animation_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(animation_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    body_physics_tests
    body_physics_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/body_physics.cpp"
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scene_pack.cpp"
)
target_include_directories(body_physics_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    transform_hierarchy_tests
    transform_hierarchy_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/transform_hierarchy.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scene_pack.cpp"
)
target_include_directories(transform_hierarchy_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    polar_graph_vm_tests
    polar_graph_vm_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/polar_kinematics.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_hierarchy.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(polar_graph_vm_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    render_substrate_tests
    render_substrate_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/render_substrate.cpp"
)
target_include_directories(render_substrate_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")

add_executable(
    polar_population_tests
    polar_population_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/graph_vm.cpp"
    "${UGTS_ANDROID_CPP_DIR}/polar_populations.cpp"
    "${UGTS_ANDROID_CPP_DIR}/polar_kinematics.cpp"
    "${UGTS_ANDROID_CPP_DIR}/render_substrate.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scatter_population.cpp"
    "${UGTS_ANDROID_CPP_DIR}/scene_pack.cpp"
    "${UGTS_ANDROID_CPP_DIR}/transform_animation.cpp"
)
target_include_directories(polar_population_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}")
target_compile_definitions(
    polar_population_tests PRIVATE
    UGTS_ENGINE_SOURCE_PATH="${UGTS_ANDROID_CPP_DIR}/engine.cpp"
    UGTS_RENDERER_SOURCE_PATH="${UGTS_ANDROID_CPP_DIR}/renderer_gles3.cpp"
    UGTS_RENDERER_HEADER_SOURCE_PATH="${UGTS_ANDROID_CPP_DIR}/renderer_gles3.hpp"
    UGTS_POLAR_SHADER_SOURCE_PATH="${UGTS_ANDROID_CPP_DIR}/../assets/shaders/polar_scene.vert"
    UGTS_SCENE_VERTEX_SOURCE_PATH="${UGTS_ANDROID_CPP_DIR}/../assets/shaders/scene.vert"
    UGTS_SCENE_FRAGMENT_SOURCE_PATH="${UGTS_ANDROID_CPP_DIR}/../assets/shaders/scene.frag"
)

add_executable(
    polar_substrate_conformance_tests
    polar_substrate_conformance_tests.cpp
    "${UGTS_ANDROID_CPP_DIR}/polar_kinematics.cpp"
)

add_executable(
    ugtc4d_decoder_tests
    ugtc4d_decoder_tests.cpp
    "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d/ugtc4d_decoder.cpp"
)
target_include_directories(
    ugtc4d_decoder_tests PRIVATE "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d"
)
target_compile_definitions(
    ugtc4d_decoder_tests PRIVATE
    UGTC4D_FIXTURE_PATH="${CMAKE_CURRENT_LIST_DIR}/fixtures/ugtc4d_native_fixture.ugtc4d"
)
set_property(TARGET ugtc4d_decoder_tests PROPERTY CXX_STANDARD 17)
set_property(TARGET ugtc4d_decoder_tests PROPERTY CXX_STANDARD_REQUIRED ON)

find_package(Threads REQUIRED)

add_executable(
    yuv_seed_capture_tests
    yuv_seed_capture_tests.cpp
    "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d/ugtc4d_decoder.cpp"
    "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d/seeded_uglut2_traversal.cpp"
    "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d/yuv_seed_capture.cpp"
)
target_include_directories(
    yuv_seed_capture_tests PRIVATE "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d"
)
target_compile_definitions(
    yuv_seed_capture_tests PRIVATE
    UGTC4D_FIXTURE_PATH="${CMAKE_CURRENT_LIST_DIR}/fixtures/ugtc4d_native_fixture.ugtc4d"
    UGLUT2_FIXTURE_PATH="${CMAKE_CURRENT_LIST_DIR}/fixtures/uglut2_native_fixture.bin"
)
set_property(TARGET yuv_seed_capture_tests PROPERTY CXX_STANDARD 17)
set_property(TARGET yuv_seed_capture_tests PROPERTY CXX_STANDARD_REQUIRED ON)
target_link_libraries(yuv_seed_capture_tests PRIVATE Threads::Threads)

add_executable(
    yuv_seed_capture_720p_benchmark
    yuv_seed_capture_720p_benchmark.cpp
    "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d/ugtc4d_decoder.cpp"
    "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d/seeded_uglut2_traversal.cpp"
    "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d/yuv_seed_capture.cpp"
)
target_include_directories(
    yuv_seed_capture_720p_benchmark PRIVATE "${CMAKE_CURRENT_LIST_DIR}/../ugtc4d"
)
target_compile_definitions(
    yuv_seed_capture_720p_benchmark PRIVATE
    UGLUT2_FIXTURE_PATH="${CMAKE_CURRENT_LIST_DIR}/fixtures/uglut2_native_fixture.bin"
)
set_property(TARGET yuv_seed_capture_720p_benchmark PROPERTY CXX_STANDARD 17)
set_property(TARGET yuv_seed_capture_720p_benchmark PROPERTY CXX_STANDARD_REQUIRED ON)
target_link_libraries(yuv_seed_capture_720p_benchmark PRIVATE Threads::Threads)
target_include_directories(
    polar_substrate_conformance_tests PRIVATE "${UGTS_ANDROID_CPP_DIR}"
)

if(MSVC)
    target_compile_options(touch_router_tests PRIVATE /W4 /permissive-)
    target_compile_options(graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(nearest_tag_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(nearest_in_cone_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(timer_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(message_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(trigger_area_tests PRIVATE /W4 /permissive-)
    target_compile_options(scatter_population_tests PRIVATE /W4 /permissive-)
    target_compile_options(transform_animation_tests PRIVATE /W4 /permissive-)
    target_compile_options(animation_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(body_physics_tests PRIVATE /W4 /permissive-)
    target_compile_options(transform_hierarchy_tests PRIVATE /W4 /permissive-)
    target_compile_options(polar_graph_vm_tests PRIVATE /W4 /permissive-)
    target_compile_options(render_substrate_tests PRIVATE /W4 /permissive-)
    target_compile_options(polar_population_tests PRIVATE /W4 /permissive-)
    target_compile_options(polar_substrate_conformance_tests PRIVATE /W4 /permissive-)
else()
    target_compile_options(touch_router_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(nearest_tag_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(nearest_in_cone_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(timer_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(message_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(trigger_area_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(scatter_population_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(transform_animation_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(animation_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(body_physics_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(transform_hierarchy_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(polar_graph_vm_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(render_substrate_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(polar_population_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(
        polar_substrate_conformance_tests PRIVATE -Wall -Wextra -Wpedantic
    )
endif()

if(MSVC)
    target_compile_options(ugtc4d_decoder_tests PRIVATE /W4 /permissive-)
    target_compile_options(yuv_seed_capture_tests PRIVATE /W4 /permissive-)
    target_compile_options(yuv_seed_capture_720p_benchmark PRIVATE /W4 /permissive-)
else()
    target_compile_options(ugtc4d_decoder_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(yuv_seed_capture_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_compile_options(
        yuv_seed_capture_720p_benchmark PRIVATE -Wall -Wextra -Wpedantic
    )
endif()
