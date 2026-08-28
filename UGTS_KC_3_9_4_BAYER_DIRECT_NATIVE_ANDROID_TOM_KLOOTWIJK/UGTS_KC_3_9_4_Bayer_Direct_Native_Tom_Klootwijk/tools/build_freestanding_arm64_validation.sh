#!/usr/bin/env bash
# Validation-only AArch64 link for environments without an Android NDK sysroot.
# The production path is the Gradle/CMake Android NDK build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/validation/freestanding_rebuild}"
TMP="$OUT/tmp"
rm -rf "$OUT"
mkdir -p "$TMP/stubs"
cat > "$TMP/stubs/libandroid_stub.c" <<'C'
typedef unsigned int u32; typedef int i32;
typedef struct ANativeActivity ANativeActivity; typedef struct ANativeWindow ANativeWindow;
typedef struct ANativeWindow_Buffer ANativeWindow_Buffer; typedef struct ARect ARect;
void ANativeActivity_setWindowFlags(ANativeActivity* a,u32 b,u32 c){}
void ANativeWindow_acquire(ANativeWindow* a){}
void ANativeWindow_release(ANativeWindow* a){}
i32 ANativeWindow_getWidth(ANativeWindow* a){return 0;}
i32 ANativeWindow_getHeight(ANativeWindow* a){return 0;}
i32 ANativeWindow_setBuffersGeometry(ANativeWindow* a,i32 b,i32 c,i32 d){return 0;}
i32 ANativeWindow_lock(ANativeWindow* a,ANativeWindow_Buffer* b,ARect* c){return 0;}
i32 ANativeWindow_unlockAndPost(ANativeWindow* a){return 0;}
C
cat > "$TMP/stubs/libc_stub.c" <<'C'
typedef unsigned long pthread_t; typedef unsigned int u32; typedef int i32;
i32 pthread_create(pthread_t* a,const void* b,void*(*c)(void*),void* d){return 0;}
i32 pthread_join(pthread_t a,void** b){return 0;}
i32 usleep(u32 a){return 0;}
C
COMMON=(--target=aarch64-linux-android26 -Oz -fPIC -ffreestanding -fno-builtin -fno-stack-protector -fno-unwind-tables -fno-asynchronous-unwind-tables -fvisibility=hidden -ffunction-sections -fdata-sections)
LINK=(-fuse-ld=lld -shared -nostdlib -Wl,-z,now,-z,relro,-z,max-page-size=16384,--gc-sections,--strip-all,--hash-style=gnu,--build-id=none)
clang "${COMMON[@]}" "${LINK[@]}" -Wl,-soname,libandroid.so "$TMP/stubs/libandroid_stub.c" -o "$TMP/stubs/libandroid.so"
clang "${COMMON[@]}" "${LINK[@]}" -Wl,-soname,libc.so "$TMP/stubs/libc_stub.c" -o "$TMP/stubs/libc.so"
clang "${COMMON[@]}" -flto -fomit-frame-pointer -c "$ROOT/app/src/main/cpp/bayer_core.c" -o "$TMP/bayer_core.o"
clang "${COMMON[@]}" -flto -fomit-frame-pointer -c "$ROOT/app/src/main/cpp/native_main.c" -o "$TMP/native_main.o"
clang --target=aarch64-linux-android26 -flto "${LINK[@]}" -Wl,-soname,libugts_kc_bayer.so \
  "$TMP/bayer_core.o" "$TMP/native_main.o" -L"$TMP/stubs" -landroid -lc \
  -o "$OUT/libugts_kc_bayer.so"
file "$OUT/libugts_kc_bayer.so"
readelf -d "$OUT/libugts_kc_bayer.so" | grep NEEDED
stat -c '%s bytes' "$OUT/libugts_kc_bayer.so"
rm -rf "$TMP"
