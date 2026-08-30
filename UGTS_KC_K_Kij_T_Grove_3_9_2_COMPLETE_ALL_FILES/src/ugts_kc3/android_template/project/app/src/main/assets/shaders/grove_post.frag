#version 300 es
precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uColor;
uniform float uTime,uBloom,uFlash,uAberration,uVignette,uSaturation,uContrast,uShock,uJuicePulse;
uniform vec2 uShockCenter;
uniform int uBayerMode;
uniform int uBayerLevels;
uniform float uBayerStrength;
uniform int uOutputHeight;
const int Bayer8[64]=int[64](
     0,48,12,60, 3,51,15,63,
    32,16,44,28,35,19,47,31,
     8,56, 4,52,11,59, 7,55,
    40,24,36,20,43,27,39,23,
     2,50,14,62, 1,49,13,61,
    34,18,46,30,33,17,45,29,
    10,58, 6,54, 9,57, 5,53,
    42,26,38,22,41,25,37,21
);
vec3 sampleRGB(vec2 uv,float shift){
    float r=texture(uColor,uv+vec2(shift,0.0)).r;
    float g=texture(uColor,uv).g;
    float b=texture(uColor,uv-vec2(shift,0.0)).b;
    return vec3(r,g,b);
}
void main(){
    vec2 uv=vUv;
    vec2 d=uv-uShockCenter;
    float dist=length(d);
    float ring=exp(-pow((dist-(0.20+uShock*0.22))/0.028,2.0))*uShock;
    vec2 warped=uv;
    if(uShock>0.001) warped += normalize(d+vec2(1e-5))*ring*0.012;
    vec3 c=sampleRGB(warped,uAberration*(0.5+ring));
    vec2 px=1.0/vec2(textureSize(uColor,0));
    float b0=max(max(c.r,c.g),c.b);
    vec3 glow=vec3(0.0);
    glow += texture(uColor,warped+px*vec2(2.0,0.0)).rgb;
    glow += texture(uColor,warped+px*vec2(-2.0,0.0)).rgb;
    glow += texture(uColor,warped+px*vec2(0.0,2.0)).rgb;
    glow += texture(uColor,warped+px*vec2(0.0,-2.0)).rgb;
    glow *= 0.25;
    float threshold=smoothstep(0.35,0.95,b0);
    c += glow*threshold*uBloom*0.65;
    c += vec3(1.0,0.72,0.42)*(uFlash*0.08+ring*0.10);
    float luma=dot(c,vec3(0.2126,0.7152,0.0722));
    c=mix(vec3(luma),c,uSaturation);
    c=(c-0.5)*uContrast+0.5;
    float vign=1.0-uVignette*smoothstep(0.25,0.78,length(uv-0.5)*1.1);
    c*=vign;
    c*=1.0+uJuicePulse*0.035;
    if(uBayerMode==0){
        fragColor=vec4(c,1.0);
        return;
    }
    vec3 src=clamp(c,0.0,1.0);
    int yTop=(uOutputHeight-1-int(gl_FragCoord.y))&7;
    ivec2 physical=ivec2(int(gl_FragCoord.x)&7,yTop);
    float bayer=float(Bayer8[physical.y*8+physical.x]);
    float t=(bayer+0.5)/64.0-0.5;
    float levelSpan=float(uBayerLevels-1);
    vec3 q=floor(src*levelSpan+0.5+t)/levelSpan;
    c=mix(src,q,uBayerStrength);
    fragColor=vec4(c,1.0);
}
