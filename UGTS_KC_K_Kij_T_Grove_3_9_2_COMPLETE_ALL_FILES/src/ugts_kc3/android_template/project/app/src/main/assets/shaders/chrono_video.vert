#version 300 es
precision highp float;

out vec2 vUv;

void main() {
    const vec2 coordinates[3]=vec2[3](
        vec2(0.0,0.0),vec2(2.0,0.0),vec2(0.0,2.0)
    );
    vec2 coordinate=coordinates[gl_VertexID];
    vUv=coordinate;
    gl_Position=vec4(coordinate*2.0-1.0,0.0,1.0);
}
