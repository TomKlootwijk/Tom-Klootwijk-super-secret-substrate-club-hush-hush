# CMake generated Testfile for 
# Source directory: U:/cpp
# Build directory: U:/cpp/build/rtx5070ti-release
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
add_test([=[ugts_chess2_native_tests]=] "U:/cpp/build/rtx5070ti-release/ugts_chess2_tests.exe")
set_tests_properties([=[ugts_chess2_native_tests]=] PROPERTIES  _BACKTRACE_TRIPLES "U:/cpp/CMakeLists.txt;89;add_test;U:/cpp/CMakeLists.txt;0;")
add_test([=[ugts_chess2_cli_selftest]=] "U:/cpp/build/rtx5070ti-release/ugts-chess2.exe" "selftest")
set_tests_properties([=[ugts_chess2_cli_selftest]=] PROPERTIES  _BACKTRACE_TRIPLES "U:/cpp/CMakeLists.txt;90;add_test;U:/cpp/CMakeLists.txt;0;")
add_test([=[ugts_chess_gpu_selftest]=] "U:/cpp/build/rtx5070ti-release/ugts-chess-gpu.exe" "self-test")
set_tests_properties([=[ugts_chess_gpu_selftest]=] PROPERTIES  _BACKTRACE_TRIPLES "U:/cpp/CMakeLists.txt;91;add_test;U:/cpp/CMakeLists.txt;0;")
