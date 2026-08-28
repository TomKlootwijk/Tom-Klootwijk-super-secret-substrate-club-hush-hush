package org.ugts.atlas.slam.core;

public final class SlamConfig {
    public int maxFeatures=1100;
    public int fastThreshold=18;
    public int maxVoxels=260000;
    public double voxelSize=0.012;
    public long keyframeMinIntervalNs=360_000_000L;
    public double keyframeTranslation=0.035;
    public double keyframeRotationRad=Math.toRadians(5.0);
    public double keyframeParallaxRad=Math.toRadians(1.0);
    public int minimumMatches=24;
    public int semiDensePixelStep=6;
    public int semiDenseDepthSamples=28;
    public int semiDenseMaxPoints=7000;
    public int overlayMapSample=2400;
    public int maxKeyframes=480;
    public int maxTrajectoryPoints=4096;
    public static SlamConfig pocoX7Pro12Gb(){return new SlamConfig();}
    public SlamConfig copy(){
        SlamConfig c=new SlamConfig();c.maxFeatures=maxFeatures;c.fastThreshold=fastThreshold;c.maxVoxels=maxVoxels;c.voxelSize=voxelSize;c.keyframeMinIntervalNs=keyframeMinIntervalNs;c.keyframeTranslation=keyframeTranslation;c.keyframeRotationRad=keyframeRotationRad;c.keyframeParallaxRad=keyframeParallaxRad;c.minimumMatches=minimumMatches;c.semiDensePixelStep=semiDensePixelStep;c.semiDenseDepthSamples=semiDenseDepthSamples;c.semiDenseMaxPoints=semiDenseMaxPoints;c.overlayMapSample=overlayMapSample;c.maxKeyframes=maxKeyframes;c.maxTrajectoryPoints=maxTrajectoryPoints;return c;
    }
}
