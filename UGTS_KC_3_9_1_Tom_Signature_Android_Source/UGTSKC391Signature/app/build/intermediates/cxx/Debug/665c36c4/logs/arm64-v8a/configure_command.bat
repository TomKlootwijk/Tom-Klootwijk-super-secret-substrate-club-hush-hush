@echo off
"C:\\Users\\Tom\\AppData\\Local\\Android\\Sdk\\cmake\\3.22.1\\bin\\cmake.exe" ^
  "-HC:\\Users\\Tom\\Documents\\theTomKlootwijkManifold\\UGTS_KC_3_9_1_Tom_Signature_Android_Source\\UGTSKC391Signature\\app\\src\\main\\cpp" ^
  "-DCMAKE_SYSTEM_NAME=Android" ^
  "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON" ^
  "-DCMAKE_SYSTEM_VERSION=26" ^
  "-DANDROID_PLATFORM=android-26" ^
  "-DANDROID_ABI=arm64-v8a" ^
  "-DCMAKE_ANDROID_ARCH_ABI=arm64-v8a" ^
  "-DANDROID_NDK=C:\\Users\\Tom\\AppData\\Local\\Android\\Sdk\\ndk\\29.0.14206865" ^
  "-DCMAKE_ANDROID_NDK=C:\\Users\\Tom\\AppData\\Local\\Android\\Sdk\\ndk\\29.0.14206865" ^
  "-DCMAKE_TOOLCHAIN_FILE=C:\\Users\\Tom\\AppData\\Local\\Android\\Sdk\\ndk\\29.0.14206865\\build\\cmake\\android.toolchain.cmake" ^
  "-DCMAKE_MAKE_PROGRAM=C:\\Users\\Tom\\AppData\\Local\\Android\\Sdk\\cmake\\3.22.1\\bin\\ninja.exe" ^
  "-DCMAKE_CXX_FLAGS=-std=c++20 -Wall -Wextra -Wpedantic" ^
  "-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=C:\\Users\\Tom\\Documents\\theTomKlootwijkManifold\\UGTS_KC_3_9_1_Tom_Signature_Android_Source\\UGTSKC391Signature\\app\\build\\intermediates\\cxx\\Debug\\665c36c4\\obj\\arm64-v8a" ^
  "-DCMAKE_RUNTIME_OUTPUT_DIRECTORY=C:\\Users\\Tom\\Documents\\theTomKlootwijkManifold\\UGTS_KC_3_9_1_Tom_Signature_Android_Source\\UGTSKC391Signature\\app\\build\\intermediates\\cxx\\Debug\\665c36c4\\obj\\arm64-v8a" ^
  "-DCMAKE_BUILD_TYPE=Debug" ^
  "-BC:\\Users\\Tom\\Documents\\theTomKlootwijkManifold\\UGTS_KC_3_9_1_Tom_Signature_Android_Source\\UGTSKC391Signature\\app\\.cxx\\Debug\\665c36c4\\arm64-v8a" ^
  -GNinja ^
  "-DANDROID_STL=c++_static" ^
  "-DUGTS_KC_PROFILE_HINT=poco_x7_pro_12gb"
