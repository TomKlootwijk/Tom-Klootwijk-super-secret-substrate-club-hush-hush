#version 450
layout(location = 0) in vec3 worldNormal;
layout(location = 0) out vec4 outColor;
layout(push_constant) uniform MaterialBlock { vec4 baseColor; } materialData;
void main() {
    vec3 L = normalize(vec3(0.5, 1.0, 0.7));
    float ndotl = max(dot(normalize(worldNormal), L), 0.0);
    vec3 color = materialData.baseColor.rgb * (0.16 + 0.84 * ndotl);
    outColor = vec4(color, materialData.baseColor.a);
}
