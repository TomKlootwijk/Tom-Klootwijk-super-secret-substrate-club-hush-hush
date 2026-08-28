package org.ugts.atlas.slam.core;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Confidence-weighted compact voxel fusion. Voxel centres are authoritative. */
public final class VoxelMap {
    private static final int BITS=21,BIAS=1<<(BITS-1),MASK=(1<<BITS)-1;
    public static final class Cell {
        public final int qx,qy,qz; private double sumX,sumY,sumZ,sumI,sumW; private int observations; private long lastFrame;
        Cell(int qx,int qy,int qz){this.qx=qx;this.qy=qy;this.qz=qz;}
        void add(Vec3 p,int intensity,double confidence,long frame){double w=Math.max(0.02,Math.min(1.0,confidence));sumX+=p.x*w;sumY+=p.y*w;sumZ+=p.z*w;sumI+=intensity*w;sumW+=w;observations++;lastFrame=frame;}
        public Vec3 average(){return sumW<=0?Vec3.ZERO:new Vec3(sumX/sumW,sumY/sumW,sumZ/sumW);}
        public int intensity(){return (int)Math.max(0,Math.min(255,Math.round(sumI/Math.max(1e-9,sumW))));}
        public double confidence(){return Math.min(1.0,0.18*Math.sqrt(observations)+0.12*Math.min(sumW,4.0));}
        public int observations(){return observations;}
        public long lastFrame(){return lastFrame;}
        double score(long now){return observations*2.0+sumW-Math.min(5.0,(now-lastFrame)*0.0002);}
    }
    private final HashMap<Long,Cell> cells=new HashMap<>();
    private double voxelSize;private int maxCells;private long frameCounter;
    public VoxelMap(double voxelSize,int maxCells){if(voxelSize<=0)throw new IllegalArgumentException();this.voxelSize=voxelSize;this.maxCells=maxCells;}
    public synchronized void add(Vec3 p,int intensity,double confidence){
        if(p==null||!p.finite())return;int qx=q(p.x),qy=q(p.y),qz=q(p.z);if(!representable(qx)||!representable(qy)||!representable(qz))return;
        long key=pack(qx,qy,qz);Cell c=cells.get(key);if(c==null){c=new Cell(qx,qy,qz);cells.put(key,c);}c.add(p,intensity,confidence,frameCounter++);
        if(cells.size()>maxCells+Math.max(128,maxCells/20))prune();
    }
    public synchronized int size(){return cells.size();}
    public synchronized double voxelSize(){return voxelSize;}
    public synchronized List<Cell> cells(){ArrayList<Cell> out=new ArrayList<>(cells.values());out.sort(Comparator.comparingInt((Cell c)->c.qx).thenComparingInt(c->c.qy).thenComparingInt(c->c.qz));return out;}
    public synchronized List<MapPoint> sample(int max){
        ArrayList<Cell> src=new ArrayList<>(cells.values());src.sort((a,b)->Double.compare(b.score(frameCounter),a.score(frameCounter)));int n=Math.min(max,src.size());ArrayList<MapPoint> out=new ArrayList<>(n);for(int i=0;i<n;i++){Cell c=src.get(i);out.add(new MapPoint(c.average(),c.intensity(),c.confidence(),c.observations()));}return out;
    }
    public synchronized void scale(double factor){
        if(!Double.isFinite(factor)||factor<=0)throw new IllegalArgumentException("scale");ArrayList<MapPoint> pts=new ArrayList<>();for(Cell c:cells.values())pts.add(new MapPoint(c.average().scale(factor),c.intensity(),c.confidence(),c.observations()));cells.clear();voxelSize*=factor;for(MapPoint p:pts)for(int i=0;i<Math.max(1,p.observations);i++)add(p.position,p.intensity,p.confidence);
    }
    public synchronized Vec3[] bounds(){if(cells.isEmpty())return new Vec3[]{Vec3.ZERO,Vec3.ZERO};double minx=Double.POSITIVE_INFINITY,miny=minx,minz=minx,maxx=-minx,maxy=-minx,maxz=-minx;for(Cell c:cells.values()){Vec3 p=c.average();minx=Math.min(minx,p.x);miny=Math.min(miny,p.y);minz=Math.min(minz,p.z);maxx=Math.max(maxx,p.x);maxy=Math.max(maxy,p.y);maxz=Math.max(maxz,p.z);}return new Vec3[]{new Vec3(minx,miny,minz),new Vec3(maxx,maxy,maxz)};}
    private void prune(){ArrayList<Map.Entry<Long,Cell>> a=new ArrayList<>(cells.entrySet());a.sort(Comparator.comparingDouble(e->e.getValue().score(frameCounter)));int remove=Math.max(1,cells.size()-maxCells);for(int i=0;i<remove;i++)cells.remove(a.get(i).getKey());}
    private int q(double v){return (int)Math.floor(v/voxelSize);}
    private boolean representable(int v){return v>=-BIAS&&v<BIAS;}
    public static long pack(int x,int y,int z){return ((long)(x+BIAS)&MASK)<<42|((long)(y+BIAS)&MASK)<<21|((long)(z+BIAS)&MASK);}
    public static int unpackX(long k){return (int)((k>>>42)&MASK)-BIAS;}
    public static int unpackY(long k){return (int)((k>>>21)&MASK)-BIAS;}
    public static int unpackZ(long k){return (int)(k&MASK)-BIAS;}
}
