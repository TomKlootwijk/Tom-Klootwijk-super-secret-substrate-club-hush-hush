package org.ugts.atlas.slam.core;
public final class MapPoint {
    public final Vec3 position;
    public final int intensity;
    public final double confidence;
    public final int observations;
    public MapPoint(Vec3 position,int intensity,double confidence,int observations){this.position=position;this.intensity=intensity;this.confidence=confidence;this.observations=observations;}
}
