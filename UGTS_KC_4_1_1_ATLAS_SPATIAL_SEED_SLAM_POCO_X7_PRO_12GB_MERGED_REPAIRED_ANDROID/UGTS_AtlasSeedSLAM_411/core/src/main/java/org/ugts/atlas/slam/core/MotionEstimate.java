package org.ugts.atlas.slam.core;

public final class MotionEstimate {
    public final boolean valid;
    public final Vec3 cameraCentreDirectionPrevious;
    public final double nominalStep;
    public final int inliers,total;
    public final double parallaxRad,quality,residual;
    public MotionEstimate(boolean valid,Vec3 direction,double nominalStep,int inliers,int total,double parallaxRad,double quality,double residual){this.valid=valid;this.cameraCentreDirectionPrevious=direction;this.nominalStep=nominalStep;this.inliers=inliers;this.total=total;this.parallaxRad=parallaxRad;this.quality=quality;this.residual=residual;}
    public static MotionEstimate invalid(int total){return new MotionEstimate(false,Vec3.ZERO,0,0,total,0,0,Double.POSITIVE_INFINITY);}
}
