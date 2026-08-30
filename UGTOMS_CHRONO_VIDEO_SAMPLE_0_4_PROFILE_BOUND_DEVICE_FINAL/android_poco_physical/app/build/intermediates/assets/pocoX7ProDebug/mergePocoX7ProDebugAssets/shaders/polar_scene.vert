#version 300 es
precision highp float;
precision highp int;

layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec3 aNormal;
// previous pose low/high, current pose low/high
layout(location = 2) in uvec4 aPolarPose;
// Legacy: authored/current NodeData Y then XYZ scale.
// Burst: per-copy height factor, base scale scalar, then two reserved lanes.
layout(location = 3) in vec4 aBaseYScale;
// Low 12 bits: deterministic lane-5 material phase. Bit 30 marks a valid KCPR
// material coordinate and bit 31 marks a generated copy for KCPR v4 Grow.
// This remains the only payload beyond the frozen 32-byte pose/scale record.
layout(location = 4) in uint aGlowPhase12;

uniform mat4 uViewProjection;
uniform float uPolarAlpha;
uniform vec4 uPolarProfile; // rhoMin, rhoMax, log(r0), radiusScale
uniform int uBurstMode;
uniform uvec4 uBurstAnchorPose; // previous low/high, current low/high
uniform vec4 uBurstRecipe; // anchor Y, duration minus one, arc height, reserved
uniform vec3 uBurstScale; // authored prototype XYZ scale
uniform int uGlowMode; // bit 0 lights with Glow; bit 1 grows generated copies
uniform vec3 uGlowRecipe; // center rho, inverse half width, strength
#ifdef POLAR_LUT
uniform sampler2D uPolarLut;
uniform int uPolarLutSize;
#endif

out vec3 vWorldPosition;
out vec3 vWorldNormal;
flat out float vPolarGlow;
flat out vec4 vPolarMaterial;

const float Tau = 6.28318530717958647692;
const uint GeneratedCopyFlag = 0x80000000u;
const uint PolarMaterialValidFlag = 0x40000000u;

void decodePose(uvec2 words,out uint rho,out uint theta,out uint heading) {
    rho=words.y>>12u;
    theta=(words.x>>26u)|((words.y&0x0fffu)<<6u);
    heading=words.x&0x0fffu;
}

uint poseTick(uvec2 words) {
    return (words.x>>12u)&0x3fffu;
}

float interpolatePeriodic(uint previous,uint current,float codeCount,float alpha) {
    float a=float(previous);
    float delta=float(current)-a;
    delta-=floor(delta/codeCount+0.5)*codeCount;
    return (a+delta*alpha)*(Tau/codeCount);
}

#ifdef POLAR_LUT
vec2 lutDirection(float angle) {
    float directionCoordinate=fract(angle/Tau)*float(uPolarLutSize);
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
    return direction;
}

vec4 lutSample(float rho,float theta) {
    vec2 direction=lutDirection(theta);
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

    float glowField=0.0;
    if ((uGlowMode&1)!=0) {
        float u=clamp(abs((rho-uGlowRecipe.x)*uGlowRecipe.y),0.0,1.0);
        float glowPulse=1.0-u*u*(3.0-2.0*u);
        float materialAngle=theta+float(aGlowPhase12&0x0fffu)*(Tau/4096.0);
#ifdef POLAR_LUT
        float materialModulation=0.5+0.5*lutDirection(materialAngle).x;
#else
        float materialModulation=0.5+0.5*cos(materialAngle);
#endif
        glowField=clamp(
            (uGlowRecipe.z*glowPulse)*materialModulation,0.0,4.0
        );
    }
    float displayGrowScale=(uGlowMode&2)!=0 &&
            (aGlowPhase12&GeneratedCopyFlag)!=0u
        ?clamp(1.0+glowField,1.0,5.0):1.0;

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

    vec2 centerXZ=radius*direction;
    float normalizedLogRadius=clamp(
        (rho-uPolarProfile.x)/(uPolarProfile.y-uPolarProfile.x),0.0,1.0
    );
    float materialPhase=float(aGlowPhase12&0x0fffu)/4096.0;
    float centerY=aBaseYScale.x;
    float burstEnvelope=1.0;
    if (uBurstMode!=0) {
        uint previousAnchorRho,previousAnchorTheta,previousAnchorHeading;
        uint currentAnchorRho,currentAnchorTheta,currentAnchorHeading;
        decodePose(
            uBurstAnchorPose.xy,
            previousAnchorRho,previousAnchorTheta,previousAnchorHeading
        );
        decodePose(
            uBurstAnchorPose.zw,
            currentAnchorRho,currentAnchorTheta,currentAnchorHeading
        );
        float anchorRho=mix(
            mix(uPolarProfile.x,uPolarProfile.y,float(previousAnchorRho)/1048575.0),
            mix(uPolarProfile.x,uPolarProfile.y,float(currentAnchorRho)/1048575.0),
            alpha
        );
        float anchorTheta=interpolatePeriodic(
            previousAnchorTheta,currentAnchorTheta,262144.0,alpha
        );
        float anchorHeading=interpolatePeriodic(
            previousAnchorHeading,currentAnchorHeading,4096.0,alpha
        );
        vec2 anchorDirection;
        vec2 anchorHeadingDirection;
        float anchorRadius;
#ifdef POLAR_LUT
        vec4 anchorSample=lutSample(anchorRho,anchorTheta);
        anchorDirection=anchorSample.xy;
        anchorRadius=anchorSample.z;
        // Reuse the same LUT interpolation for packed anchor heading.  The
        // radius lane is deliberately ignored for this direction-only sample.
        anchorHeadingDirection=lutSample(uPolarProfile.x,anchorHeading).xy;
#else
        anchorDirection=vec2(cos(anchorTheta),sin(anchorTheta));
        anchorRadius=exp(
            uPolarProfile.z+clamp(anchorRho,uPolarProfile.x,uPolarProfile.y)
        );
        anchorHeadingDirection=vec2(cos(anchorHeading),sin(anchorHeading));
#endif
        vec2 localCenter=centerXZ;
        centerXZ=anchorRadius*anchorDirection+vec2(
            anchorHeadingDirection.x*localCenter.x+
                anchorHeadingDirection.y*localCenter.y,
            -anchorHeadingDirection.y*localCenter.x+
                anchorHeadingDirection.x*localCenter.y
        );
        uint previousCombinedHeading=
            (previousAnchorHeading+previousHeading)&0x0fffu;
        uint currentCombinedHeading=
            (currentAnchorHeading+currentHeading)&0x0fffu;
        heading=interpolatePeriodic(
            previousCombinedHeading,currentCombinedHeading,4096.0,alpha
        );
        float interpolatedTick=mix(
            float(poseTick(aPolarPose.xy)),float(poseTick(aPolarPose.zw)),alpha
        );
        float age=clamp(interpolatedTick/max(uBurstRecipe.y,1.0),0.0,1.0);
        burstEnvelope=(4.0*age)*(1.0-age);
        centerY=uBurstRecipe.x+
            (uBurstRecipe.z*aBaseYScale.x)*burstEnvelope;
    }

    vec3 instanceScale=aBaseYScale.yzw;
    vec3 normalScale=instanceScale;
    if (uBurstMode!=0) {
        float displayScale=aBaseYScale.y*burstEnvelope;
        normalScale=uBurstScale*aBaseYScale.y;
        instanceScale=uBurstScale*displayScale;
    }
    // Authored/random scale, then Burst envelope, then the display-only Grow
    // multiplier. The high phase flag keeps the real prototype at 1.0.
    instanceScale*=displayGrowScale;
    vec3 scaledPosition=aPosition*instanceScale;
#ifdef POLAR_LUT
    vec2 headingDirection=lutDirection(heading);
    float headingCosine=headingDirection.x;
    float headingSine=headingDirection.y;
#else
    float headingCosine=cos(heading);
    float headingSine=sin(heading);
#endif
    vec3 rotatedPosition=vec3(
        headingCosine*scaledPosition.x+headingSine*scaledPosition.z,
        scaledPosition.y,
        -headingSine*scaledPosition.x+headingCosine*scaledPosition.z
    );
    vec3 center=vec3(radius*direction.x,aBaseYScale.x,radius*direction.y);
    if (uBurstMode!=0) center=vec3(centerXZ.x,centerY,centerXZ.y);
    vec3 worldPosition=center+rotatedPosition;

    vec3 inverseScaledNormal=aNormal/normalScale;
    vWorldNormal=normalize(vec3(
        headingCosine*inverseScaledNormal.x+headingSine*inverseScaledNormal.z,
        inverseScaledNormal.y,
        -headingSine*inverseScaledNormal.x+headingCosine*inverseScaledNormal.z
    ));
    vWorldPosition=worldPosition;
    vPolarGlow=glowField;
    vPolarMaterial=(aGlowPhase12&PolarMaterialValidFlag)!=0u
        ?vec4(normalizedLogRadius,direction,materialPhase)
        :vec4(0.0,0.0,0.0,-1.0);
    gl_Position=uViewProjection*vec4(worldPosition,1.0);
}
