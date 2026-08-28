#version 300 es
precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uLuma;
uniform int uMode;
uniform float uPulse;
const int B[64]=int[64](
 0,32,8,40,2,34,10,42,48,16,56,24,50,18,58,26,
 12,44,4,36,14,46,6,38,60,28,52,20,62,30,54,22,
 3,35,11,43,1,33,9,41,51,19,59,27,49,17,57,25,
 15,47,7,39,13,45,5,37,63,31,55,23,61,29,53,21);
void main(){
    ivec2 px=ivec2(gl_FragCoord.xy);
    float y=texture(uLuma,clamp(vUv,vec2(0.0),vec2(1.0))).r;
    float d=(float(B[(px.y&7)*8+(px.x&7)])+0.5)/64.0-0.5;
    float q=clamp(floor(y*5.0+d+uPulse*0.02)/4.0,0.0,1.0);
    vec3 tint=uMode==0?vec3(0.76,1.0,0.78):(uMode==1?vec3(0.55,0.92,1.0):vec3(1.0,0.78,0.42));
    vec3 c=mix(vec3(0.005,0.008,0.012),tint,q);
    fragColor=vec4(c,1.0);
}
