#ifndef UGTS_EGL_GLES_MIN_H
#define UGTS_EGL_GLES_MIN_H

// Minimal EGL + OpenGL ES declarations used by the headless benchmark.
// This intentionally avoids an engine dependency and keeps the package self-contained.

#include <cstddef>
#include <cstdint>

using EGLDisplay = void*;
using EGLConfig = void*;
using EGLContext = void*;
using EGLSurface = void*;
using EGLNativeDisplayType = void*;
using EGLint = std::int32_t;
using EGLBoolean = std::uint32_t;
using EGLenum = std::uint32_t;

#define EGL_DEFAULT_DISPLAY ((EGLNativeDisplayType)0)
#define EGL_NO_DISPLAY ((EGLDisplay)0)
#define EGL_NO_CONTEXT ((EGLContext)0)
#define EGL_NO_SURFACE ((EGLSurface)0)
#define EGL_FALSE 0
#define EGL_TRUE 1
#define EGL_NONE 0x3038
#define EGL_SURFACE_TYPE 0x3033
#define EGL_PBUFFER_BIT 0x0001
#define EGL_RENDERABLE_TYPE 0x3040
#define EGL_OPENGL_ES3_BIT 0x0040
#define EGL_RED_SIZE 0x3024
#define EGL_GREEN_SIZE 0x3023
#define EGL_BLUE_SIZE 0x3022
#define EGL_ALPHA_SIZE 0x3021
#define EGL_WIDTH 0x3057
#define EGL_HEIGHT 0x3056
#define EGL_CONTEXT_CLIENT_VERSION 0x3098
#define EGL_OPENGL_ES_API 0x30A0
#define EGL_VENDOR 0x3053
#define EGL_VERSION 0x3054
#define EGL_EXTENSIONS 0x3055

// ANGLE/SwiftShader headless platform attributes.
#define EGL_PLATFORM_ANGLE_ANGLE 0x3202
#define EGL_PLATFORM_ANGLE_TYPE_ANGLE 0x3203
#define EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE 0x3450
#define EGL_PLATFORM_ANGLE_DEVICE_TYPE_ANGLE 0x3209
#define EGL_PLATFORM_ANGLE_DEVICE_TYPE_SWIFTSHADER_ANGLE 0x3487
#define EGL_PLATFORM_ANGLE_NATIVE_PLATFORM_TYPE_ANGLE 0x348F
#define EGL_PLATFORM_VULKAN_DISPLAY_MODE_HEADLESS_ANGLE 0x34A5

using PFNEGLGETPLATFORMDISPLAYEXTPROC = EGLDisplay (*)(EGLenum, void*, const EGLint*);

extern "C" {
EGLBoolean eglInitialize(EGLDisplay, EGLint*, EGLint*);
EGLBoolean eglTerminate(EGLDisplay);
EGLBoolean eglBindAPI(EGLenum);
EGLBoolean eglChooseConfig(EGLDisplay, const EGLint*, EGLConfig*, EGLint, EGLint*);
EGLSurface eglCreatePbufferSurface(EGLDisplay, EGLConfig, const EGLint*);
EGLContext eglCreateContext(EGLDisplay, EGLConfig, EGLContext, const EGLint*);
EGLBoolean eglDestroyContext(EGLDisplay, EGLContext);
EGLBoolean eglDestroySurface(EGLDisplay, EGLSurface);
EGLBoolean eglMakeCurrent(EGLDisplay, EGLSurface, EGLSurface, EGLContext);
void* eglGetProcAddress(const char*);
const char* eglQueryString(EGLDisplay, EGLint);
EGLint eglGetError(void);
}

using GLenum = std::uint32_t;
using GLuint = std::uint32_t;
using GLint = std::int32_t;
using GLsizei = std::int32_t;
using GLchar = char;
using GLboolean = std::uint8_t;
using GLbitfield = std::uint32_t;
using GLsizeiptr = std::intptr_t;
using GLintptr = std::intptr_t;
using GLint64 = std::int64_t;
using GLuint64 = std::uint64_t;
using GLubyte = unsigned char;

#define GL_FALSE 0
#define GL_TRUE 1
#define GL_COMPUTE_SHADER 0x91B9
#define GL_COMPILE_STATUS 0x8B81
#define GL_LINK_STATUS 0x8B82
#define GL_INFO_LOG_LENGTH 0x8B84
#define GL_PROGRAM_BINARY_LENGTH 0x8741
#define GL_PROGRAM_BINARY_RETRIEVABLE_HINT 0x8257
#define GL_NUM_PROGRAM_BINARY_FORMATS 0x87FE
#define GL_PROGRAM_BINARY_FORMATS 0x87FF
#define GL_SHADER_STORAGE_BUFFER 0x90D2
#define GL_STATIC_DRAW 0x88E4
#define GL_DYNAMIC_DRAW 0x88E8
#define GL_MAP_READ_BIT 0x0001
#define GL_MAP_WRITE_BIT 0x0002
#define GL_SHADER_STORAGE_BARRIER_BIT 0x2000
#define GL_BUFFER_UPDATE_BARRIER_BIT 0x0200
#define GL_VENDOR 0x1F00
#define GL_RENDERER 0x1F01
#define GL_VERSION 0x1F02
#define GL_SHADING_LANGUAGE_VERSION 0x8B8C
#define GL_EXTENSIONS 0x1F03
#define GL_MAX_COMPUTE_WORK_GROUP_COUNT 0x91BE
#define GL_MAX_COMPUTE_WORK_GROUP_SIZE 0x91BF
#define GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS 0x90EB
#define GL_MAX_COMPUTE_SHARED_MEMORY_SIZE 0x8262
#define GL_MAX_COMPUTE_SHADER_STORAGE_BLOCKS 0x90DB
#define GL_MAX_SHADER_STORAGE_BUFFER_BINDINGS 0x90DD
#define GL_MAX_SHADER_STORAGE_BLOCK_SIZE 0x90DE
#define GL_NO_ERROR 0

extern "C" {
const GLubyte* glGetString(GLenum);
const GLubyte* glGetStringi(GLenum, GLuint);
void glGetIntegerv(GLenum, GLint*);
void glGetInteger64v(GLenum, GLint64*);
void glGetIntegeri_v(GLenum, GLuint, GLint*);
GLenum glGetError(void);

GLuint glCreateShader(GLenum);
void glDeleteShader(GLuint);
void glShaderSource(GLuint, GLsizei, const GLchar* const*, const GLint*);
void glCompileShader(GLuint);
void glGetShaderiv(GLuint, GLenum, GLint*);
void glGetShaderInfoLog(GLuint, GLsizei, GLsizei*, GLchar*);

GLuint glCreateProgram(void);
void glDeleteProgram(GLuint);
void glAttachShader(GLuint, GLuint);
void glDetachShader(GLuint, GLuint);
void glProgramParameteri(GLuint, GLenum, GLint);
void glLinkProgram(GLuint);
void glGetProgramiv(GLuint, GLenum, GLint*);
void glGetProgramInfoLog(GLuint, GLsizei, GLsizei*, GLchar*);
void glGetProgramBinary(GLuint, GLsizei, GLsizei*, GLenum*, void*);
void glProgramBinary(GLuint, GLenum, const void*, GLsizei);
void glUseProgram(GLuint);

void glGenBuffers(GLsizei, GLuint*);
void glDeleteBuffers(GLsizei, const GLuint*);
void glBindBuffer(GLenum, GLuint);
void glBufferData(GLenum, GLsizeiptr, const void*, GLenum);
void glBufferSubData(GLenum, GLintptr, GLsizeiptr, const void*);
void glBindBufferBase(GLenum, GLuint, GLuint);
void* glMapBufferRange(GLenum, GLintptr, GLsizeiptr, GLbitfield);
GLboolean glUnmapBuffer(GLenum);

void glDispatchCompute(GLuint, GLuint, GLuint);
void glMemoryBarrier(GLbitfield);
void glFinish(void);
}

#endif  // UGTS_EGL_GLES_MIN_H
