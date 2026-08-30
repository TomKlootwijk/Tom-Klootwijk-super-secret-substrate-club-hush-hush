#version 300 es
#extension GL_OES_EGL_image_external_essl3 : require
precision highp float;
precision highp int;

uniform samplerExternalOES uVideo;
uniform mat4 uSurfaceTransform;
uniform ivec2 uSourceSize;
uniform ivec2 uOutputSize;

out vec4 fragColor;

void main() {
    // The preview is already a derived log-polar raster. This path is a copy;
    // it deliberately has no UGCVLUT1 uniform and cannot apply the LUT twice.
    ivec2 outputPixel=ivec2(
        int(gl_FragCoord.x),uOutputSize.y-1-int(gl_FragCoord.y)
    );
    vec2 topLeftUv=(vec2(outputPixel)+vec2(0.5))/vec2(uSourceSize);
    vec2 glUv=vec2(topLeftUv.x,1.0-topLeftUv.y);
    vec2 externalUv=(uSurfaceTransform*vec4(glUv,0.0,1.0)).xy;
    fragColor=texture(uVideo,externalUv);
}
