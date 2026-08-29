package org.ugts.atlas.slam.core;

public final class Triangulator {
    public static final class Result {public final Vec3 point;public final double rayGap,parallaxRad,reprojection;Result(Vec3 p,double gap,double parallax,double reprojection){point=p;rayGap=gap;parallaxRad=parallax;this.reprojection=reprojection;}}
    public Result triangulate(Pose a,Pose b,CameraModel camera,Feature fa,Feature fb){
        Vec3 d1=a.directionCameraToWorld(camera.ray(fa.x,fa.y)).normalized(),d2=b.directionCameraToWorld(camera.ray(fb.x,fb.y)).normalized();
        double[] st=VisualInertialEstimator.closestRayParameters(a.position,d1,b.position,d2);if(st==null||st[0]<=0||st[1]<=0)return null;
        double parallax=Math.acos(Vec3.clamp(d1.dot(d2),-1,1));if(parallax<Math.toRadians(0.55)||parallax>Math.toRadians(65))return null;
        Vec3 p1=a.position.add(d1.scale(st[0])),p2=b.position.add(d2.scale(st[1])),p=Vec3.lerp(p1,p2,0.5);double gap=p1.distance(p2);
        double[] pa=camera.project(a.worldToCamera(p)),pb=camera.project(b.worldToCamera(p));if(pa==null||pb==null)return null;
        double e=Math.hypot(pa[0]-fa.x,pa[1]-fa.y)+Math.hypot(pb[0]-fb.x,pb[1]-fb.y);
        double baseline=a.position.distance(b.position);if(gap>Math.max(0.02,baseline*0.12)||e>4.5)return null;
        return new Result(p,gap,parallax,e*0.5);
    }
}
