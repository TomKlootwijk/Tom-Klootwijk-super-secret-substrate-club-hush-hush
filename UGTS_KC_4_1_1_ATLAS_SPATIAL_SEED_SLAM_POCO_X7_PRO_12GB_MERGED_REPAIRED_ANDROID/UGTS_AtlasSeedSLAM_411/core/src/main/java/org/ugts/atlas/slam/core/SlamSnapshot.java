package org.ugts.atlas.slam.core;

import java.util.Collections;
import java.util.List;

public final class SlamSnapshot {
    public final String state,scaleState;
    public final long frameId,timestampNs;
    public final int imageWidth,imageHeight,featureCount,matchCount,inlierCount,keyframeCount,mapPointCount;
    public final double trackingQuality,parallaxRad,metricScale;
    public final Pose pose;
    public final float[] featureXY;
    public final List<MapPoint> mapSample;
    public final List<Vec3> trajectory;
    public SlamSnapshot(String state,String scaleState,long frameId,long timestampNs,int w,int h,int featureCount,int matchCount,int inlierCount,int keyframes,int mapPoints,double quality,double parallax,double metricScale,Pose pose,float[] featureXY,List<MapPoint> mapSample,List<Vec3> trajectory){this.state=state;this.scaleState=scaleState;this.frameId=frameId;this.timestampNs=timestampNs;this.imageWidth=w;this.imageHeight=h;this.featureCount=featureCount;this.matchCount=matchCount;this.inlierCount=inlierCount;this.keyframeCount=keyframes;this.mapPointCount=mapPoints;this.trackingQuality=quality;this.parallaxRad=parallax;this.metricScale=metricScale;this.pose=pose;this.featureXY=featureXY;this.mapSample=Collections.unmodifiableList(mapSample);this.trajectory=Collections.unmodifiableList(trajectory);}
}
