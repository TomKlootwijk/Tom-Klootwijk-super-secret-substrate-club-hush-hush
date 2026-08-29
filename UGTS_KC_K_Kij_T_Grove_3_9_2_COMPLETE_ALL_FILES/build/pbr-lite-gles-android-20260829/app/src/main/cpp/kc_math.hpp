#pragma once
#include <algorithm>
#include <array>
#include <cmath>

namespace kc {

constexpr float kPi = 3.14159265358979323846f;

struct Vec3 {
    float x = 0.0f, y = 0.0f, z = 0.0f;
};

struct Quat {
    float w = 1.0f, x = 0.0f, y = 0.0f, z = 0.0f;
};

struct Mat4 {
    std::array<float, 16> v{};
    float& operator()(int row, int col) { return v[static_cast<std::size_t>(col * 4 + row)]; }
    float operator()(int row, int col) const { return v[static_cast<std::size_t>(col * 4 + row)]; }
    const float* data() const { return v.data(); }
};

inline Vec3 operator+(Vec3 a, Vec3 b) { return {a.x+b.x, a.y+b.y, a.z+b.z}; }
inline Vec3 operator-(Vec3 a, Vec3 b) { return {a.x-b.x, a.y-b.y, a.z-b.z}; }
inline Vec3 operator*(Vec3 a, float s) { return {a.x*s, a.y*s, a.z*s}; }
inline Vec3 operator/(Vec3 a, float s) { return {a.x/s, a.y/s, a.z/s}; }
inline float dot(Vec3 a, Vec3 b) { return a.x*b.x + a.y*b.y + a.z*b.z; }
inline Vec3 cross(Vec3 a, Vec3 b) {
    return {a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x};
}
inline float length(Vec3 a) { return std::sqrt(dot(a,a)); }
inline Vec3 normalize(Vec3 a) {
    const float n = length(a);
    return n > 1.0e-8f ? a / n : Vec3{0.0f, 1.0f, 0.0f};
}
inline float clamp(float value, float lo, float hi) { return std::max(lo, std::min(hi, value)); }

inline Quat normalize(Quat q) {
    const float n = std::sqrt(q.w*q.w + q.x*q.x + q.y*q.y + q.z*q.z);
    return n > 1.0e-8f ? Quat{q.w/n,q.x/n,q.y/n,q.z/n} : Quat{};
}
inline Quat multiply(Quat a, Quat b) {
    return {
        a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z,
        a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,
        a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x,
        a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w
    };
}
inline Quat axisAngle(Vec3 axis, float angle) {
    axis = normalize(axis);
    const float half = angle * 0.5f;
    const float s = std::sin(half);
    return normalize({std::cos(half), axis.x*s, axis.y*s, axis.z*s});
}

inline Mat4 identity() {
    Mat4 m;
    m(0,0)=m(1,1)=m(2,2)=m(3,3)=1.0f;
    return m;
}
inline Mat4 multiply(const Mat4& a, const Mat4& b) {
    Mat4 out;
    for (int col=0; col<4; ++col)
        for (int row=0; row<4; ++row)
            for (int k=0; k<4; ++k)
                out(row,col) += a(row,k)*b(k,col);
    return out;
}
inline Mat4 translation(Vec3 p) {
    Mat4 m = identity();
    m(0,3)=p.x; m(1,3)=p.y; m(2,3)=p.z;
    return m;
}
inline Mat4 scaling(Vec3 s) {
    Mat4 m = identity();
    m(0,0)=s.x; m(1,1)=s.y; m(2,2)=s.z;
    return m;
}
inline Mat4 rotation(Quat q) {
    q = normalize(q);
    const float xx=q.x*q.x, yy=q.y*q.y, zz=q.z*q.z;
    const float xy=q.x*q.y, xz=q.x*q.z, yz=q.y*q.z;
    const float wx=q.w*q.x, wy=q.w*q.y, wz=q.w*q.z;
    Mat4 m = identity();
    m(0,0)=1-2*(yy+zz); m(0,1)=2*(xy-wz);   m(0,2)=2*(xz+wy);
    m(1,0)=2*(xy+wz);   m(1,1)=1-2*(xx+zz); m(1,2)=2*(yz-wx);
    m(2,0)=2*(xz-wy);   m(2,1)=2*(yz+wx);   m(2,2)=1-2*(xx+yy);
    return m;
}
inline Mat4 trs(Vec3 p, Quat q, Vec3 s) {
    return multiply(translation(p), multiply(rotation(q), scaling(s)));
}
inline Mat4 perspective(float fovyRadians, float aspect, float nearPlane, float farPlane) {
    Mat4 m;
    const float f = 1.0f/std::tan(fovyRadians*0.5f);
    m(0,0)=f/aspect;
    m(1,1)=f;
    m(2,2)=(farPlane+nearPlane)/(nearPlane-farPlane);
    m(2,3)=(2.0f*farPlane*nearPlane)/(nearPlane-farPlane);
    m(3,2)=-1.0f;
    return m;
}
inline Mat4 lookAt(Vec3 eye, Vec3 target, Vec3 up) {
    const Vec3 f = normalize(target-eye);
    const Vec3 s = normalize(cross(f,up));
    const Vec3 u = cross(s,f);
    Mat4 m = identity();
    m(0,0)=s.x; m(0,1)=s.y; m(0,2)=s.z; m(0,3)=-dot(s,eye);
    m(1,0)=u.x; m(1,1)=u.y; m(1,2)=u.z; m(1,3)=-dot(u,eye);
    m(2,0)=-f.x; m(2,1)=-f.y; m(2,2)=-f.z; m(2,3)=dot(f,eye);
    return m;
}

} // namespace kc
