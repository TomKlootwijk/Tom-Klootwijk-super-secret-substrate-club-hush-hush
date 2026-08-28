#version 450
layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;
layout(set = 0, binding = 0) uniform CameraBlock { mat4 viewProj; } cameraData;
layout(push_constant) uniform InstanceBlock { mat4 world; uint materialIndex; } instanceData;
layout(location = 0) out vec3 worldNormal;
void main() {
    gl_Position = cameraData.viewProj * instanceData.world * vec4(inPosition, 1.0);
    worldNormal = normalize(mat3(instanceData.world) * inNormal);
}
