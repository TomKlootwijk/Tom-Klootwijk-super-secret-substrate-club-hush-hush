#version 300 es
precision highp float;

in vec3 vWorldPosition;
in vec3 vWorldNormal;

uniform vec4 uBaseColor;
uniform float uMetallic;
uniform float uRoughness;
uniform vec3 uEmissive;
uniform vec3 uCameraPosition;
uniform vec3 uLightDirection;
uniform vec3 uLightColor;
uniform float uLightIntensity;
uniform float uAmbient;
uniform float uPulse;

out vec4 fragColor;

void main() {
    vec3 n = normalize(vWorldNormal);
    vec3 l = normalize(-uLightDirection);
    vec3 v = normalize(uCameraPosition - vWorldPosition);
    vec3 halfway = l + v;
    float halfwayLength2 = dot(halfway, halfway);
    vec3 h = halfwayLength2 <= 1.0e-12
        ? vec3(0.0)
        : halfway * inversesqrt(halfwayLength2);
    float ndotl = max(dot(n, l), 0.0);
    float ndotv = max(dot(n, v), 0.0);
    float ndoth = max(dot(n, h), 0.0);

    float metallic = clamp(uMetallic, 0.0, 1.0);
    float rough = clamp(uRoughness, 0.0, 1.0);
    float smoothness = 1.0 - rough;
    float smooth2 = smoothness * smoothness;
    vec3 f0 = mix(vec3(0.04), uBaseColor.rgb, metallic);

    float oneMinusNdotV = 1.0 - ndotv;
    float fresnel2 = oneMinusNdotV * oneMinusNdotV;
    float fresnel4 = fresnel2 * fresnel2;
    float fresnel = fresnel4 * oneMinusNdotV;
    vec3 specColor = f0 + (vec3(1.0) - f0) * fresnel;

    float ndoth2 = ndoth * ndoth;
    float ndoth4 = ndoth2 * ndoth2;
    float ndoth8 = ndoth4 * ndoth4;
    float ndoth16 = ndoth8 * ndoth8;
    float lobe = mix(ndoth4, ndoth16, smooth2);

    float diffuse = (1.0 - metallic) *
        (uAmbient + uLightIntensity * ndotl * (0.65 + 0.35 * rough));
    float spec = uLightIntensity * ndotl * lobe * (0.25 + 1.75 * smoothness);
    vec3 rim = fresnel4 * f0 * (0.03 + 0.07 * smoothness);
    vec3 lit = uLightColor * (uBaseColor.rgb * diffuse + specColor * spec) + rim;
    lit += uEmissive * (1.0 + 0.25 * uPulse);
    fragColor = vec4(lit, uBaseColor.a);
}
