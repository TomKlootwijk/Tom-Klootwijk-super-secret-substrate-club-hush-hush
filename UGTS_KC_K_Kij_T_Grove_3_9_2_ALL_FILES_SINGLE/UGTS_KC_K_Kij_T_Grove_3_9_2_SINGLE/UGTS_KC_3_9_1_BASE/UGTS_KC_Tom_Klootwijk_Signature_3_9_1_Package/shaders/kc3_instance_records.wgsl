// KC Two Hands 3.0 WGSL layout prototype.
// This file is a portability contract, not a measured production renderer.

struct InstanceRecord {
    world0 : vec4<f32>,
    world1 : vec4<f32>,
    world2 : vec4<f32>,
    world3 : vec4<f32>,
    bounds_min : vec4<f32>,
    bounds_max : vec4<f32>,
    pattern_opcode : u32,
    parameter_offset : u32,
    material_index : u32,
    derivative_flags : u32,
    support_mask : u32,
    compatibility_mask : u32,
    lineage_hash : u32,
    reserved : u32,
};

struct EventProposal {
    event_time : f32,
    guard_value : f32,
    numeric_error : f32,
    confidence : f32,
    entity_index : u32,
    guard_status : u32,
    priority : i32,
    lineage_hash : u32,
};

@group(0) @binding(0) var<storage, read> instances : array<InstanceRecord>;
@group(0) @binding(1) var<storage, read> parameters : array<vec4<f32>>;
@group(0) @binding(2) var<storage, read_write> proposals : array<EventProposal>;

fn superellipse_radius(theta : f32, exponent : f32) -> vec2<f32> {
    let c = cos(theta);
    let s = sin(theta);
    let p = 2.0 / max(exponent, 0.0001);
    return vec2<f32>(sign(c) * pow(abs(c), p), sign(s) * pow(abs(s), p));
}

@compute @workgroup_size(64)
fn evaluate_instances(@builtin(global_invocation_id) gid : vec3<u32>) {
    let i = gid.x;
    if (i >= arrayLength(&instances)) { return; }
    let instance = instances[i];
    // Production implementation dispatches by pattern_opcode and writes only bounded proposals.
    // Authoritative gameplay commit remains outside this shader.
    if (instance.pattern_opcode == 0u) {
        proposals[i] = EventProposal(0.0, 1.0, 0.0, 0.0, i, 0u, 0, instance.lineage_hash);
    }
}
