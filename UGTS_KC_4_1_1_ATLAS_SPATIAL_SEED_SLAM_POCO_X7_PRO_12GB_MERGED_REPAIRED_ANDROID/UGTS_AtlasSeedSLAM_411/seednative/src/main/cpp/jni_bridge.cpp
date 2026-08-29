#include <jni.h>
#include <cstdint>
#include "seed_core.h"

extern "C" JNIEXPORT jint JNICALL
Java_org_ugts_atlas_seednative_NativeSeedBridge_nativeAbiVersion(
        JNIEnv*, jclass) {
    return static_cast<jint>(ugts_seed::kAbiVersion);
}

extern "C" JNIEXPORT jboolean JNICALL
Java_org_ugts_atlas_seednative_NativeSeedBridge_nativeSelfTest(
        JNIEnv*, jclass) {
    return ugts_seed::self_test() ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jint JNICALL
Java_org_ugts_atlas_seednative_NativeSeedBridge_nativeCrc32(
        JNIEnv* env, jclass, jbyteArray input) {
    if (input == nullptr) {
        return 0;
    }
    const jsize length = env->GetArrayLength(input);
    jbyte* bytes = env->GetByteArrayElements(input, nullptr);
    if (bytes == nullptr) {
        return 0;
    }
    const std::uint32_t value = ugts_seed::crc32(
            reinterpret_cast<const std::uint8_t*>(bytes),
            static_cast<std::size_t>(length));
    env->ReleaseByteArrayElements(input, bytes, JNI_ABORT);
    return static_cast<jint>(value);
}

extern "C" JNIEXPORT jint JNICALL
Java_org_ugts_atlas_seednative_NativeSeedBridge_nativeScheduleBounded(
        JNIEnv*, jclass,
        jlong seedHigh, jlong seedLow, jlong stream, jlong index, jint bound) {
    if (bound <= 0) {
        return 0;
    }
    return static_cast<jint>(ugts_seed::schedule_bounded(
            static_cast<std::uint64_t>(seedHigh),
            static_cast<std::uint64_t>(seedLow),
            static_cast<std::uint64_t>(stream),
            static_cast<std::uint64_t>(index),
            static_cast<std::uint32_t>(bound)));
}
