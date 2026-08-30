#version 300 es
precision highp float;
precision highp int;

layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec3 aNormal;
// previous pose low/high, current pose low/high
layout(location = 2) in uvec4 aPolarPose;
// authored/current NodeData Y followed by XYZ scale
layout(location = 3) in vec4 aBaseYScale;

uniform mat4 uViewProjection;
uniform float uPolarAlpha;
uniform vec4 uPolarProfile; // rhoMin, rhoMax, log(r0), radiusScale
#ifdef POLAR_LUT
uniform sampler2D uPolarLut;
uniform int uPolarLutSize;
#endif

out vec3 vWorldPosition;
out vec3 vWorldNormal;

const float Tau = 6.28318530717958647692;

void decodePose(uvec2 words,out uint rho,out uint theta,out uint heading) {
    rho=words.y>>12u;
    theta=(words.x>>26u)|((words.y&0x0fffu)<<6u);
    heading=words.x&0x0fffu;
}

float interpolatePeriodic(uint previous,uint current,float codeCount,float alpha) {
    float a=float(previous);
    float delta=float(current)-a;
    delta-=floor(delta/codeCount+0.5)*codeCount;
    return (a+delta*alpha)*(Tau/codeCount);
}

#ifdef POLAR_LUT
vec4 lutSample(float rho,float theta) {
    float directionCoordinate=fract(theta/Tau)*float(uPolarLutSize);
    int directionLow=int(floor(directionCoordinate));
    float directionFraction=fract(directionCoordinate);
    vec2 direction=mix(
        texelFetch(uPolarLut,ivec2(directionLow,0),0).xy,
        texelFetch(uPolarLut,ivec2(directionLow+1,0),0).xy,
        directionFraction
    );
    float directionLength2=dot(direction,direction);
    direction=directionLength2>1.0e-12
        ? direction*inversesqrt(directionLength2)
        : texelFetch(uPolarLut,ivec2(directionLow,0),0).xy;

    float radiusCoordinate=clamp(
        (rho-uPolarProfile.x)/(uPolarProfile.y-uPolarProfile.x),0.0,1.0
    )*float(uPolarLutSize-1);
    int radiusLow=int(floor(radiusCoordinate));
    int radiusHigh=min(uPolarLutSize-1,radiusLow+1);
    float normalizedRadius=mix(
        texelFetch(uPolarLut,ivec2(radiusLow,0),0).z,
        texelFetch(uPolarLut,ivec2(radiusHigh,0),0).z,
        fract(radiusCoordinate)
    );
    return vec4(direction,normalizedRadius*uPolarProfile.w,0.0);
}
#endif

void main() {
    uint previousRho,previousTheta,previousHeading;
    uint currentRho,currentTheta,currentHeading;
    decodePose(aPolarPose.xy,previousRho,previousTheta,previousHeading);
    decodePose(aPolarPose.zw,currentRho,currentTheta,currentHeading);
    float alpha=clamp(uPolarAlpha,0.0,1.0);
    float rho=mix(
        mix(uPolarProfile.x,uPolarProfile.y,float(previousRho)/1048575.0),
        mix(uPolarProfile.x,uPolarProfile.y,float(currentRho)/1048575.0),
        alpha
    );
    float theta=interpolatePeriodic(previousTheta,currentTheta,262144.0,alpha);
    float heading=interpolatePeriodic(previousHeading,currentHeading,4096.0,alpha);

    vec2 direction;
    float radius;
#ifdef POLAR_LUT
        vec4 sampleValue=lutSample(rho,theta);
        direction=sampleValue.xy;
        radius=sampleValue.z;
#else
        direction=vec2(cos(theta),sin(theta));
        radius=exp(uPolarProfile.z+clamp(rho,uPolarProfile.x,uPolarProfile.y));
#endif

    vec3 instanceScale=aBaseYScale.yzw;
    vec3 scaledPosition=aPosition*instanceScale;
    float headingSine=sin(heading);
    float headingCosine=cos(heading);
    vec3 rotatedPosition=vec3(
        headingCosine*scaledPosition.x+headingSine*scaledPosition.z,
        scaledPosition.y,
        -headingSine*scaledPosition.x+headingCosine*scaledPosition.z
    );
    vec3 center=vec3(radius*direction.x,aBaseYScale.x,radius*direction.y);
    vec3 worldPosition=center+rotatedPosition;

    vec3 inverseScaledNormal=aNormal/instanceScale;
    vWorldNormal=normalize(vec3(
        headingCosine*inverseScaledNormal.x+headingSine*inverseScaledNormal.z,
        inverseScaledNormal.y,
        -headingSine*inverseScaledNormal.x+headingCosine*inverseScaledNormal.z
    ));
    vWorldPosition=worldPosition;
    gl_Position=uViewProjection*vec4(worldPosition,1.0);
}
