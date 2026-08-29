#version 300 es
precision highp float;

layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec4 aInstanceModel0;
layout(location = 3) in vec4 aInstanceModel1;
layout(location = 4) in vec4 aInstanceModel2;
layout(location = 5) in vec4 aInstanceModel3;

uniform mat4 uViewProjection;
uniform mat4 uModel;
uniform bool uInstanced;

out vec3 vWorldPosition;
out vec3 vWorldNormal;

void main() {
    mat4 model = uInstanced
        ? mat4(aInstanceModel0, aInstanceModel1, aInstanceModel2, aInstanceModel3)
        : uModel;
    vec4 world = model * vec4(aPosition, 1.0);
    vWorldPosition = world.xyz;
    vWorldNormal = normalize(mat3(model) * aNormal);
    gl_Position = uViewProjection * world;
}
