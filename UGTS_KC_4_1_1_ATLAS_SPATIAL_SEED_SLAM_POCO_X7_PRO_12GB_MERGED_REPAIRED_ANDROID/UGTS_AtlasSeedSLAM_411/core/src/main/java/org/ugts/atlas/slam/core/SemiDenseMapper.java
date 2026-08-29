package org.ugts.atlas.slam.core;

/** Gradient-selected plane sweep between adjacent keyframes. */
public final class SemiDenseMapper {
    public int fuse(Keyframe a,Keyframe b,VoxelMap map,SlamConfig cfg){
        double baseline=a.pose.position.distance(b.pose.position);if(baseline<1e-5)return 0;
        GrayFrame fa=a.frame,fb=b.frame;if(fa==null||fb==null)return 0;CameraModel cam=a.camera;int step=Math.max(4,cfg.semiDensePixelStep),added=0;
        double minDepth=Math.max(baseline*1.6,0.035),maxDepth=Math.max(minDepth*3,baseline*90.0);int samples=Math.max(12,cfg.semiDenseDepthSamples);
        for(int y=18;y<fa.height-18&&added<cfg.semiDenseMaxPoints;y+=step){
            for(int x=18;x<fa.width-18&&added<cfg.semiDenseMaxPoints;x+=step){
                int grad=fa.gradientL1(x,y);if(grad<26)continue;
                double best=Double.POSITIVE_INFINITY,second=Double.POSITIVE_INFINITY,bestDepth=0;
                Vec3 ray=cam.ray(x,y);
                for(int si=0;si<samples;si++){
                    double u=(double)si/(samples-1);double inv=(1.0/minDepth)*(1-u)+(1.0/maxDepth)*u;double depth=1.0/inv;
                    Vec3 world=a.pose.cameraToWorld(ray.scale(depth));Vec3 inB=b.pose.worldToCamera(world);double[] p=cam.project(inB);if(p==null||!cam.inside(p[0],p[1],4))continue;
                    double cost=patchCost(fa,x,y,fb,p[0],p[1]);if(cost<best){second=best;best=cost;bestDepth=depth;}else if(cost<second)second=cost;
                }
                if(bestDepth<=0||best>420||!(best<second*0.78))continue;
                Vec3 world=a.pose.cameraToWorld(ray.scale(bestDepth));Vec3 inB=b.pose.worldToCamera(world);double[] p=cam.project(inB);if(p==null)continue;
                // Reverse neighbourhood guard rejects one-sided photometric minima.
                double reverse=patchCost(fb,p[0],p[1],fa,x,y);if(Math.abs(reverse-best)>90)continue;
                double conf=Vec3.clamp((1.0-best/420.0)*(grad/100.0),0.06,0.88);map.add(world,fa.u8(x,y),conf);added++;
            }
        }return added;
    }
    private double patchCost(GrayFrame a,double ax,double ay,GrayFrame b,double bx,double by){double meanA=0,meanB=0;int n=0;for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++){meanA+=a.sample(ax+dx,ay+dy);meanB+=b.sample(bx+dx,by+dy);n++;}meanA/=n;meanB/=n;double s=0;for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++){double da=a.sample(ax+dx,ay+dy)-meanA,db=b.sample(bx+dx,by+dy)-meanB,d=da-db;s+=d*d;}return s/n;}
}
