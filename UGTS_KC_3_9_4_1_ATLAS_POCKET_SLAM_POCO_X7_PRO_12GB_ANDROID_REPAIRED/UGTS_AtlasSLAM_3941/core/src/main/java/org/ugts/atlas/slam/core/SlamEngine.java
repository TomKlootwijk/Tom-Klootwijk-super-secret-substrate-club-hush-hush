package org.ugts.atlas.slam.core;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Offline monocular visual-inertial sparse/semi-dense scanner. Observations
 * become map mutations only after descriptor, epipolar, parallax and
 * reprojection guards. Metric labels remain disabled until an anchor is set.
 */
public final class SlamEngine {
    public enum State {IDLE,SCANNING,PAUSED,FINISHED}
    private final SlamConfig config;
    private final FastBrief detector=new FastBrief();
    private final DescriptorMatcher matcher=new DescriptorMatcher();
    private final VisualInertialEstimator motionEstimator=new VisualInertialEstimator();
    private final Triangulator triangulator=new Triangulator();
    private final SemiDenseMapper semiDense=new SemiDenseMapper();
    private VoxelMap map;
    private final ArrayList<Keyframe> keyframes=new ArrayList<>();
    private final ArrayList<Vec3> trajectory=new ArrayList<>();
    private final ArrayList<LedgerEvent> ledger=new ArrayList<>();
    private State state=State.IDLE;private String sessionId="";private long startedNs,endedNs,frameId,eventSeq;
    private GrayFrame previousFrame;private List<Feature> previousFeatures;private Pose previousPose=Pose.IDENTITY;private Quat orientationOrigin,previousOrientation;
    private Keyframe lastKeyframe;private CameraModel camera;private double metricScale=1.0;private boolean scaleCalibrated;
    private SlamSnapshot lastSnapshot;

    public SlamEngine(SlamConfig config){this.config=config.copy();resetContainers();}
    private void resetContainers(){map=new VoxelMap(config.voxelSize,config.maxVoxels);keyframes.clear();trajectory.clear();ledger.clear();previousFrame=null;previousFeatures=null;lastKeyframe=null;camera=null;lastSnapshot=null;}
    public synchronized void start(String sessionId,long nowNs){resetContainers();this.sessionId=sessionId==null?"session":sessionId;startedNs=nowNs;endedNs=0;frameId=0;eventSeq=0;metricScale=1;scaleCalibrated=false;orientationOrigin=null;previousOrientation=null;previousPose=Pose.IDENTITY;state=State.SCANNING;event(nowNs,"session_started","accepted",fields("session_id",this.sessionId));}
    public synchronized void pause(long nowNs){if(state==State.SCANNING){state=State.PAUSED;event(nowNs,"capture_paused","accepted",fields());}}
    public synchronized void resume(long nowNs){if(state==State.PAUSED){state=State.SCANNING;previousFrame=null;previousFeatures=null;event(nowNs,"capture_resumed","accepted",fields());}}
    public synchronized void finish(long nowNs){if(state==State.SCANNING||state==State.PAUSED){state=State.FINISHED;endedNs=nowNs;if(lastKeyframe!=null)lastKeyframe.releaseHeavyData();event(nowNs,"session_finished","accepted",fields("frames",Long.toString(frameId),"voxels",Integer.toString(map.size())));}}
    public synchronized State state(){return state;}

    public synchronized SlamSnapshot process(GrayFrame frame,CameraModel cameraModel,Quat absoluteOrientation,Vec3 inertialDisplacementHint){
        if(state!=State.SCANNING)return lastSnapshot;
        if(frame==null||cameraModel==null)return lastSnapshot;
        frameId++;camera=cameraModel;
        Quat abs=absoluteOrientation==null?Quat.IDENTITY:absoluteOrientation;
        if(orientationOrigin==null)orientationOrigin=abs;
        Quat orientation=orientationOrigin.conjugate().multiply(abs);
        List<Feature> features=detector.detect(frame,config.maxFeatures,config.fastThreshold);
        List<Match> matches=new ArrayList<>();MotionEstimate motion=MotionEstimate.invalid(0);Pose pose=previousPose;
        if(previousFrame==null){
            pose=new Pose(orientation,Vec3.ZERO);commitKeyframe(frame,features,pose,MotionEstimate.invalid(0));
            event(frame.timestampNs,"tracking_initialized","accepted",fields("features",Integer.toString(features.size()),"intrinsics",camera.source));
        }else{
            matches=matcher.match(previousFeatures,features);
            motion=motionEstimator.estimate(previousFeatures,features,matches,camera,previousPose.orientation,orientation,config.minimumMatches);
            if(motion.valid){
                double step=motion.nominalStep;
                if(inertialDisplacementHint!=null&&inertialDisplacementHint.finite()){
                    double n=inertialDisplacementHint.norm();if(n>0.002&&n<0.25)step=0.78*step+0.22*n;
                }
                Vec3 deltaWorld=previousPose.orientation.rotate(motion.cameraCentreDirectionPrevious.scale(step));
                pose=new Pose(orientation,previousPose.position.add(deltaWorld));
            } else {
                pose=new Pose(orientation,previousPose.position);
            }
            boolean keyframe=shouldKeyframe(frame,pose,motion,features.size());
            if(keyframe)commitKeyframe(frame,features,pose,motion);
            if(frameId%30==0)event(frame.timestampNs,"tracking_checkpoint",motion.valid?"accepted":"deferred",fields("matches",Integer.toString(matches.size()),"inliers",Integer.toString(motion.inliers),"quality",fmt(motion.quality)));
        }
        previousFrame=frame;previousFeatures=features;previousPose=pose;previousOrientation=orientation;trajectory.add(pose.position);
        if(trajectory.size()>config.maxTrajectoryPoints)decimateTrajectory();
        float[] xy=new float[features.size()*2];for(int i=0;i<features.size();i++){xy[i*2]=features.get(i).x;xy[i*2+1]=features.get(i).y;}
        lastSnapshot=new SlamSnapshot(state.name().toLowerCase(Locale.ROOT),scaleCalibrated?"metric_anchor":"relative_units",frameId,frame.timestampNs,frame.width,frame.height,features.size(),matches.size(),motion.inliers,keyframes.size(),map.size(),motion.quality,motion.parallaxRad,metricScale,pose,xy,map.sample(config.overlayMapSample),new ArrayList<>(trajectory));
        return lastSnapshot;
    }


    private void decimateTrajectory(){
        if(trajectory.size()<=2)return;
        ArrayList<Vec3> compact=new ArrayList<>((trajectory.size()+1)/2);
        for(int i=0;i<trajectory.size();i+=2)compact.add(trajectory.get(i));
        Vec3 last=trajectory.get(trajectory.size()-1);
        if(compact.get(compact.size()-1)!=last)compact.add(last);
        trajectory.clear();trajectory.addAll(compact);
    }

    private boolean shouldKeyframe(GrayFrame frame,Pose pose,MotionEstimate motion,int features){
        if(lastKeyframe==null)return true;long dt=frame.timestampNs-lastKeyframe.timestampNs;if(dt<config.keyframeMinIntervalNs)return false;
        return pose.translationDistance(lastKeyframe.pose)>=config.keyframeTranslation||pose.rotationDistance(lastKeyframe.pose)>=config.keyframeRotationRad||motion.parallaxRad>=config.keyframeParallaxRad||features<config.minimumMatches*2;
    }
    private void commitKeyframe(GrayFrame frame,List<Feature> features,Pose pose,MotionEstimate motion){
        if(keyframes.size()>=config.maxKeyframes){event(frame.timestampNs,"keyframe_proposal","rejected",fields("reason","keyframe_limit"));return;}
        Keyframe current=new Keyframe(keyframes.size(),frame.timestampNs,pose,camera,frame,features);
        int sparse=0,dense=0;
        if(lastKeyframe!=null){
            List<Match> km=matcher.match(lastKeyframe.features,current.features);
            for(Match m:km){Triangulator.Result r=triangulator.triangulate(lastKeyframe.pose,current.pose,camera,lastKeyframe.features.get(m.previousIndex),current.features.get(m.currentIndex));if(r!=null){int intensity=frame.u8(Math.max(0,Math.min(frame.width-1,Math.round(current.features.get(m.currentIndex).x))),Math.max(0,Math.min(frame.height-1,Math.round(current.features.get(m.currentIndex).y))));double conf=Vec3.clamp((1.0-m.distance/90.0)*(1.0-r.reprojection/5.0),0.05,0.96);map.add(r.point,intensity,conf);sparse++;}}
            if(sparse>=12&&motion.quality>=0.08)dense=semiDense.fuse(lastKeyframe,current,map,config);
            int loop=findLoopCandidate(current);if(loop>=0)event(frame.timestampNs,"loop_closure_proposal","deferred",fields("current_keyframe",Long.toString(current.id),"candidate_keyframe",Integer.toString(loop),"reason","requires_geometric_bundle_adjustment"));
        }
        keyframes.add(current);
        if(lastKeyframe!=null)lastKeyframe.releaseHeavyData();
        lastKeyframe=current;
        event(frame.timestampNs,"keyframe_committed","accepted",fields("keyframe",Long.toString(current.id),"features",Integer.toString(features.size()),"sparse_points",Integer.toString(sparse),"semi_dense_points",Integer.toString(dense),"map_voxels",Integer.toString(map.size())));
    }
    private int findLoopCandidate(Keyframe current){int best=-1,bestD=99;for(int i=0;i<keyframes.size()-12;i++){if(i%2!=0)continue;int d=Long.bitCount(current.signature^keyframes.get(i).signature);if(d<bestD){bestD=d;best=i;}}return bestD<=13?best:-1;}
    public synchronized Vec3 currentPosition(){return previousPose.position;}
    public synchronized boolean applyKnownDistanceAnchor(Vec3 start,Vec3 end,double metres,long nowNs){
        if(start==null||end==null||!Double.isFinite(metres)||metres<=0)return false;double relative=start.distance(end);if(relative<1e-5)return false;double factor=metres/relative;
        map.scale(factor);for(int i=0;i<keyframes.size();i++)keyframes.get(i).pose=keyframes.get(i).pose.scaled(factor);for(int i=0;i<trajectory.size();i++)trajectory.set(i,trajectory.get(i).scale(factor));previousPose=previousPose.scaled(factor);metricScale*=factor;scaleCalibrated=true;
        event(nowNs,"metric_scale_anchor","accepted",fields("known_metres",fmt(metres),"relative_distance",fmt(relative),"factor",fmt(factor)));return true;
    }
    public synchronized SlamSnapshot snapshot(){return lastSnapshot;}
    public synchronized SessionData sessionData(){return new SessionData(sessionId,scaleCalibrated?"metric_anchor":"relative_units",camera==null?"unknown":camera.source,startedNs,endedNs==0?System.nanoTime():endedNs,frameId,metricScale,map.voxelSize(),camera!=null&&camera.calibrated,map.cells(),new ArrayList<>(keyframes),new ArrayList<>(ledger));}
    private void event(long ts,String type,String commit,Map<String,String> fields){ledger.add(new LedgerEvent(eventSeq++,ts,type,commit,fields));}
    private static Map<String,String> fields(String... kv){LinkedHashMap<String,String>m=new LinkedHashMap<>();for(int i=0;i+1<kv.length;i+=2)m.put(kv[i],kv[i+1]);return m;}
    private static String fmt(double v){return String.format(Locale.ROOT,"%.8g",v);}
}
