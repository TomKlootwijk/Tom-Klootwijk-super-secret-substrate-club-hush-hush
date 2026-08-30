#version 300 es
#extension GL_OES_EGL_image_external_essl3 : require
precision highp float;
precision highp int;

uniform samplerExternalOES uVideo;
uniform highp usampler2D uLut;
uniform mat4 uSurfaceTransform;
uniform ivec2 uSourceSize;
uniform ivec2 uOutputSize;

out vec4 fragColor;

uvec4 decodedRgba8(ivec2 topLeftPixel) {
    // UGCVLUT1 indices address the canonical top-left source raster. Convert
    // that exact pixel center to GL bottom-left coordinates first, then apply
    // Android's required SurfaceTexture producer transform.
    vec2 topLeftUv=(vec2(topLeftPixel)+vec2(0.5))/vec2(uSourceSize);
    vec2 glUv=vec2(topLeftUv.x,1.0-topLeftUv.y);
    vec2 externalUv=(uSurfaceTransform*vec4(glUv,0.0,1.0)).xy;
    vec4 decoded=clamp(texture(uVideo,externalUv),0.0,1.0);
    return uvec4(floor(decoded*255.0+0.5));
}

void main() {
    // FBO fragments are bottom-left indexed. Flip once so the LUT lookup is
    // canonical top-left, while the owned texture still displays upright.
    ivec2 outputPixel=ivec2(
        int(gl_FragCoord.x),uOutputSize.y-1-int(gl_FragCoord.y)
    );
    uvec4 address=texelFetch(uLut,outputPixel,0);
    if (address.w==0u) {
        fragColor=vec4(0.0,0.0,0.0,1.0);
        return;
    }
    ivec2 p00=ivec2(address.xy);
    uint fx=address.z&255u;
    uint fy=(address.z>>8u)&255u;
    uint ix=256u-fx;
    uint iy=256u-fy;
    uint w00=ix*iy;
    uint w10=fx*iy;
    uint w01=ix*fy;
    uint w11=fx*fy;
    uvec4 sum=
        decodedRgba8(p00)*w00+
        decodedRgba8(p00+ivec2(1,0))*w10+
        decodedRgba8(p00+ivec2(0,1))*w01+
        decodedRgba8(p00+ivec2(1,1))*w11;
    uvec4 quantized=(sum+uvec4(32768u))>>16u;
    fragColor=vec4(quantized)/255.0;
}
