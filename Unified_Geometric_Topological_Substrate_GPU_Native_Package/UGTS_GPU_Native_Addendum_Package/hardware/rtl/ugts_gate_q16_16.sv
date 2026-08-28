// UGTS-GN 1.1 reference fixed-function support/compatibility/guard gate.
// Numeric profile: signed Q16.16 x/y/z and pre-normalized axis components.
// radius_sq, cone_cos_sq and guard_sq use unsigned Q32.32.
// This module is a transparent combinational reference. Insert pipeline registers
// to meet the target clock and validate all saturation/range assumptions.
module ugts_gate_q16_16 (
    input  logic signed [31:0] x,
    input  logic signed [31:0] y,
    input  logic signed [31:0] z,
    input  logic signed [31:0] ax,
    input  logic signed [31:0] ay,
    input  logic signed [31:0] az,
    input  logic        [63:0] radius_sq,
    input  logic        [63:0] cone_cos_sq,
    input  logic        [63:0] guard_sq,
    input  logic        [15:0] compatibility_mask,
    input  logic         [3:0] mode_bit,
    input  logic         [7:0] sheet,
    input  logic         [7:0] target_sheet,
    input  logic               orientation,
    input  logic               target_orientation,
    output logic               in_support,
    output logic               compatible,
    output logic               guard_crossed,
    output logic               verified
);
    logic signed [63:0] xx, yy, zz;
    logic signed [63:0] xax, yay, zaz;
    logic        [65:0] r2;
    logic signed [65:0] dot;
    logic       [131:0] dot_sq;
    logic       [129:0] angular_rhs;
    logic        [65:0] radial_delta;
    logic               radial_ok, angular_ok, mode_ok;

    always_comb begin
        xx = x * x;
        yy = y * y;
        zz = z * z;
        xax = x * ax;
        yay = y * ay;
        zaz = z * az;
        r2 = {2'b0, xx[63:0]} + {2'b0, yy[63:0]} + {2'b0, zz[63:0]};
        dot = {{2{xax[63]}},xax} + {{2{yay[63]}},yay} + {{2{zaz[63]}},zaz};
        dot_sq = $unsigned(dot * dot);              // Q64.64
        angular_rhs = r2 * cone_cos_sq;             // Q64.64
        radial_ok = (r2 <= {2'b0, radius_sq});
        angular_ok = (!dot[65]) && (dot_sq >= {{2{1'b0}}, angular_rhs});
        in_support = radial_ok && angular_ok;
        mode_ok = compatibility_mask[mode_bit];
        compatible = mode_ok && (sheet == target_sheet) &&
                     (orientation == target_orientation);
        radial_delta = (r2 >= {2'b0, radius_sq}) ?
                       (r2 - {2'b0, radius_sq}) :
                       ({2'b0, radius_sq} - r2);
        guard_crossed = radial_delta <= {2'b0, guard_sq};
        verified = in_support && compatible && guard_crossed;
    end
endmodule
