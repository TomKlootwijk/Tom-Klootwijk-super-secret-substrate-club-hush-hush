package org.ugts.atlas.slam.core;

public final class Feature {
    public final int id;
    public final float x,y;
    public final int score;
    public final long d0,d1,d2,d3;
    public Feature(int id,float x,float y,int score,long d0,long d1,long d2,long d3){this.id=id;this.x=x;this.y=y;this.score=score;this.d0=d0;this.d1=d1;this.d2=d2;this.d3=d3;}
    public int distance(Feature b){return Long.bitCount(d0^b.d0)+Long.bitCount(d1^b.d1)+Long.bitCount(d2^b.d2)+Long.bitCount(d3^b.d3);}
    public int chunk16(int table){long v=table<2?(table==0?d0:d1):(table==2?d2:d3);return (int)(v&0xffffL);}
}
