package org.ugts.atlas.slam.core;

public final class CameraModel {
    public final int width,height;
    public final double fx,fy,cx,cy;
    public final boolean calibrated;
    public final String source;
    public CameraModel(int width,int height,double fx,double fy,double cx,double cy,boolean calibrated,String source){
        if(width<=0||height<=0||fx<=0||fy<=0)throw new IllegalArgumentException("invalid camera model");
        this.width=width;this.height=height;this.fx=fx;this.fy=fy;this.cx=cx;this.cy=cy;this.calibrated=calibrated;this.source=source==null?"unknown":source;
    }
    public Vec3 ray(double x,double y){return new Vec3((x-cx)/fx,(y-cy)/fy,1.0).normalized();}
    public double[] project(Vec3 p){if(p.z<=1e-9)return null;return new double[]{fx*p.x/p.z+cx,fy*p.y/p.z+cy};}
    public boolean inside(double x,double y,double margin){return x>=margin&&x<width-margin&&y>=margin&&y<height-margin;}
    public CameraModel scaledTo(int w,int h){double sx=(double)w/width,sy=(double)h/height;return new CameraModel(w,h,fx*sx,fy*sy,cx*sx,cy*sy,calibrated,source);}
    public static CameraModel declaredFallback(int w,int h){double f=0.86*Math.max(w,h);return new CameraModel(w,h,f,f,(w-1)*0.5,(h-1)*0.5,false,"declared_fallback");}
}
