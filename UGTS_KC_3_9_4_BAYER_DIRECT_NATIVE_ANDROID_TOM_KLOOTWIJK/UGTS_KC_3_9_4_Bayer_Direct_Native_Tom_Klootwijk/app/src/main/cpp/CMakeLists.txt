cmake_minimum_required(VERSION 3.22.1)
project(ugts_kc_bayer_direct C)

add_library(ugts_kc_bayer SHARED
    native_main.c
    bayer_core.c
)

target_compile_features(ugts_kc_bayer PRIVATE c_std_11)
target_compile_options(ugts_kc_bayer PRIVATE
    -Oz
    -flto
    -ffunction-sections
    -fdata-sections
    -fvisibility=hidden
    -fomit-frame-pointer
    -fno-stack-protector
    -fno-unwind-tables
    -fno-asynchronous-unwind-tables
)
target_link_options(ugts_kc_bayer PRIVATE
    -flto
    -Wl,--gc-sections
    -Wl,--strip-all
    -Wl,--build-id=none
)
target_link_libraries(ugts_kc_bayer PRIVATE android)
