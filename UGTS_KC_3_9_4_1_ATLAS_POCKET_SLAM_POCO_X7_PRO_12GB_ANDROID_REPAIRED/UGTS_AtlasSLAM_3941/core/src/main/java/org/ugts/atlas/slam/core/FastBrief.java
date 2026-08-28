package org.ugts.atlas.slam.core;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Deterministic FAST-9 detector plus a fixed 256-bit BRIEF descriptor. */
public final class FastBrief {
    private static final int[] CX={0,3,5,6,5,3,0,-3,-5,-6,-5,-3,0,3,5,6};
    private static final int[] CY={-6,-5,-3,0,3,5,6,5,3,0,-3,-5,-6,-5,-3,0};
    private static final int[] AX=new int[256],AY=new int[256],BX=new int[256],BY=new int[256];
    static {
        long s=0x9e3779b97f4a7c15L;
        for(int i=0;i<256;i++){
            s=xorshift(s);AX[i]=Math.floorMod(s,27)-13;
            s=xorshift(s);AY[i]=Math.floorMod(s,27)-13;
            s=xorshift(s);BX[i]=Math.floorMod(s,27)-13;
            s=xorshift(s);BY[i]=Math.floorMod(s,27)-13;
        }
    }
    private static long xorshift(long x){x^=x<<13;x^=x>>>7;x^=x<<17;return x;}
    private static final class Candidate {int x,y,score;Candidate(int x,int y,int score){this.x=x;this.y=y;this.score=score;}}

    public List<Feature> detect(GrayFrame f,int maxFeatures,int baseThreshold){
        int w=f.width,h=f.height,border=16;
        int threshold=adaptiveThreshold(f,baseThreshold);
        int[] scores=new int[w*h];
        for(int y=border;y<h-border;y+=1){
            int row=y*w;
            for(int x=border;x<w-border;x++){
                int c=f.u8(x,y),score=fastScore(f,x,y,c,threshold);
                if(score>0)scores[row+x]=score;
            }
        }
        int cell=28,perCell=5;
        ArrayList<Candidate> selected=new ArrayList<>();
        for(int y0=border;y0<h-border;y0+=cell){
            for(int x0=border;x0<w-border;x0+=cell){
                ArrayList<Candidate> local=new ArrayList<>();
                int y1=Math.min(h-border,y0+cell),x1=Math.min(w-border,x0+cell);
                for(int y=y0;y<y1;y++)for(int x=x0;x<x1;x++){
                    int s=scores[y*w+x];if(s==0)continue;
                    boolean max=true;
                    for(int yy=y-1;yy<=y+1&&max;yy++)for(int xx=x-1;xx<=x+1;xx++)if(scores[yy*w+xx]>s){max=false;break;}
                    if(max)local.add(new Candidate(x,y,s));
                }
                local.sort((a,b)->Integer.compare(b.score,a.score));
                for(int i=0;i<Math.min(perCell,local.size());i++)selected.add(local.get(i));
            }
        }
        selected.sort((a,b)->Integer.compare(b.score,a.score));
        int n=Math.min(maxFeatures,selected.size());ArrayList<Feature> out=new ArrayList<>(n);
        for(int i=0;i<n;i++){
            Candidate p=selected.get(i);long[] d=brief(f,p.x,p.y);out.add(new Feature(i,p.x,p.y,p.score,d[0],d[1],d[2],d[3]));
        }
        return out;
    }
    private int adaptiveThreshold(GrayFrame f,int base){
        long sum=0;int count=0;int sx=Math.max(8,f.width/32),sy=Math.max(8,f.height/24);
        for(int y=2;y<f.height-2;y+=sy)for(int x=2;x<f.width-2;x+=sx){sum+=f.gradientL1(x,y);count++;}
        int texture=count==0?base:(int)(sum/count/6);return Math.max(10,Math.min(34,(base*3+texture)/4));
    }
    private int fastScore(GrayFrame f,int x,int y,int c,int t){
        int best=0;
        for(int sign:new int[]{1,-1}){
            int run=0,score=0;
            for(int k=0;k<24;k++){
                int i=k&15,d=sign*(f.u8(x+CX[i],y+CY[i])-c);
                if(d>t){run++;score+=d;if(run>=9)best=Math.max(best,score);}else{run=0;score=0;}
            }
        }
        return best;
    }
    private long[] brief(GrayFrame f,int x,int y){
        long[] d=new long[4];
        for(int i=0;i<256;i++)if(f.u8(x+AX[i],y+AY[i])<f.u8(x+BX[i],y+BY[i]))d[i>>>6]|=1L<<(i&63);
        return d;
    }
}
