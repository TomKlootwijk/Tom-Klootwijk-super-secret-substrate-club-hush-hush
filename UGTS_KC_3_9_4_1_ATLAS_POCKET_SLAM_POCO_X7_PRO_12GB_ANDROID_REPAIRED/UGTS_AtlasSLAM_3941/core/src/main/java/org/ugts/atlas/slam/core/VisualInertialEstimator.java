package org.ugts.atlas.slam.core;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Uses the IMU rotation to remove rotational flow, then solves the epipolar
 * translation direction as the smallest eigenvector of sum(n n^T), where
 * n = b2 cross (R b1). Scale remains explicit and is calibrated separately.
 */
public final class VisualInertialEstimator {
    public MotionEstimate estimate(List<Feature> previous,List<Feature> current,List<Match> matches,CameraModel camera,Quat worldFromPrev,Quat worldFromCurrent,int minimumInliers){
        if(matches.size()<minimumInliers)return MotionEstimate.invalid(matches.size());
        Quat currentFromPrevious=worldFromCurrent.conjugate().multiply(worldFromPrev);
        ArrayList<Vec3> normals=new ArrayList<>(matches.size());ArrayList<Double> parallaxes=new ArrayList<>(matches.size());
        for(Match m:matches){
            Vec3 b1=camera.ray(previous.get(m.previousIndex).x,previous.get(m.previousIndex).y);
            Vec3 b2=camera.ray(current.get(m.currentIndex).x,current.get(m.currentIndex).y);
            Vec3 rb1=currentFromPrevious.rotate(b1);Vec3 n=b2.cross(rb1);
            if(n.norm()>1e-7){normals.add(n.normalized());double d=Vec3.clamp(b2.dot(rb1),-1,1);parallaxes.add(Math.acos(d));}
        }
        if(normals.size()<minimumInliers)return MotionEstimate.invalid(matches.size());
        double[][] a=accumulate(normals,null);Vec3 t=SymmetricEigen3.smallest(a);
        double threshold=Math.sin(Math.toRadians(1.6));
        boolean[] inlier=new boolean[normals.size()];int count=0;double residual=0;
        for(int i=0;i<normals.size();i++){double r=Math.abs(normals.get(i).dot(t));if(r<threshold){inlier[i]=true;count++;residual+=r;}}
        if(count<minimumInliers)return MotionEstimate.invalid(matches.size());
        a=accumulate(normals,inlier);t=SymmetricEigen3.smallest(a);count=0;residual=0;
        for(Vec3 n:normals){double r=Math.abs(n.dot(t));if(r<threshold){count++;residual+=r;}}
        Quat previousFromCurrent=currentFromPrevious.conjugate();
        Vec3 centreDirection=previousFromCurrent.rotate(t.scale(-1)).normalized(); // C2 = -R^T t
        if(directionSignScore(previous,current,matches,camera,currentFromPrevious,centreDirection)<0)centreDirection=centreDirection.scale(-1);
        Collections.sort(parallaxes);double parallax=parallaxes.get(parallaxes.size()/2);
        double step=Vec3.clamp(parallax*0.62,0.006,0.12);
        double ratio=(double)count/normals.size();double q=ratio*Vec3.clamp(parallax/Math.toRadians(3.0),0.05,1.0);
        return new MotionEstimate(true,centreDirection,step,count,matches.size(),parallax,q,residual/Math.max(1,count));
    }
    private double[][] accumulate(List<Vec3> n,boolean[] use){double[][]a=new double[3][3];for(int i=0;i<n.size();i++){if(use!=null&&!use[i])continue;Vec3 v=n.get(i);double[]x={v.x,v.y,v.z};for(int r=0;r<3;r++)for(int c=0;c<3;c++)a[r][c]+=x[r]*x[c];}return a;}
    private int directionSignScore(List<Feature>a,List<Feature>b,List<Match>matches,CameraModel cam,Quat currentFromPrevious,Vec3 centrePrev){
        int score=0,limit=Math.min(matches.size(),120);
        for(int i=0;i<limit;i++){
            Match m=matches.get(i);Vec3 d1=cam.ray(a.get(m.previousIndex).x,a.get(m.previousIndex).y);Vec3 d2Prev=currentFromPrevious.conjugate().rotate(cam.ray(b.get(m.currentIndex).x,b.get(m.currentIndex).y));
            double[] st=closestRayParameters(Vec3.ZERO,d1,centrePrev,d2Prev);if(st!=null)score+=(st[0]>0&&st[1]>0)?1:-1;
        }return score;
    }
    static double[] closestRayParameters(Vec3 o1,Vec3 d1,Vec3 o2,Vec3 d2){double a=d1.dot(d1),b=d1.dot(d2),c=d2.dot(d2);Vec3 w=o1.sub(o2);double d=d1.dot(w),e=d2.dot(w),den=a*c-b*b;if(Math.abs(den)<1e-9)return null;return new double[]{(b*e-c*d)/den,(a*e-b*d)/den};}
}
