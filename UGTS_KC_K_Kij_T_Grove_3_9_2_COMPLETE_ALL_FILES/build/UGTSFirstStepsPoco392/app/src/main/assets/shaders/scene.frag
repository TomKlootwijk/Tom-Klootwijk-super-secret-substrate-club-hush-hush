#version 300 es
precision highp float;

in vec3 vWorldPosition;
in vec3 vWorldNormal;

uniform vec4 uBaseColor;
uniform vec3 uEmissive;
uniform vec3 uLightDirection;
uniform vec3 uLightColor;
uniform float uLightIntensity;
uniform float uAmbient;
uniform float uPulse;

out vec4 fragColor;

void main() {
    vec3 n = normalize(vWorldNormal);
    float diffuse = max(dot(n, normalize(-uLightDirection)), 0.0);
    float rim = pow(1.0 - max(dot(n, normalize(vec3(0.2, 0.7, 0.6))), 0.0), 3.0);
    vec3 lit = uBaseColor.rgb * (uAmbient + diffuse * uLightColor * uLightIntensity);
    lit += uEmissive * (1.0 + 0.25 * uPulse) + rim * 0.06;
    fragColor = vec4(lit, uBaseColor.a);
}
