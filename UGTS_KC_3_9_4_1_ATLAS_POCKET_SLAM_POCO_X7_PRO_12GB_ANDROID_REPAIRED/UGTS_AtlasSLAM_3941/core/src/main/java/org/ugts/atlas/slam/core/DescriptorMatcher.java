package org.ugts.atlas.slam.core;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Four-table descriptor LSH with ratio and mutual-best guards. */
public final class DescriptorMatcher {
    private static final class IntBag {int[] a=new int[8];int n;void add(int v){if(n==a.length){int[]b=new int[a.length*2];System.arraycopy(a,0,b,0,n);a=b;}a[n++]=v;}}
    public List<Match> match(List<Feature> previous,List<Feature> current){
        ArrayList<Match> out=new ArrayList<>();if(previous.isEmpty()||current.isEmpty())return out;
        ArrayList<Map<Integer,IntBag>> tables=new ArrayList<>(4);
        for(int t=0;t<4;t++){Map<Integer,IntBag> m=new HashMap<>();for(int i=0;i<previous.size();i++)m.computeIfAbsent(previous.get(i).chunk16(t),k->new IntBag()).add(i);tables.add(m);}
        int[] stamp=new int[previous.size()];int token=1;int[] candidate=new int[Math.max(64,previous.size())];
        int[] bestForPrev=new int[previous.size()];int[] distForPrev=new int[previous.size()];java.util.Arrays.fill(bestForPrev,-1);java.util.Arrays.fill(distForPrev,999);
        ArrayList<Match> provisional=new ArrayList<>();
        for(int ci=0;ci<current.size();ci++,token++){
            Feature c=current.get(ci);int cn=0;
            for(int t=0;t<4;t++){IntBag b=tables.get(t).get(c.chunk16(t));if(b==null)continue;for(int k=0;k<b.n;k++){int pi=b.a[k];if(stamp[pi]!=token){stamp[pi]=token;if(cn==candidate.length)break;candidate[cn++]=pi;}}}
            if(cn<3){ // deterministic sparse fallback for descriptors with no exact chunk collision
                int stride=Math.max(1,previous.size()/96);for(int pi=ci%stride;pi<previous.size()&&cn<candidate.length;pi+=stride)if(stamp[pi]!=token){stamp[pi]=token;candidate[cn++]=pi;}
            }
            int best=999,second=999,bpi=-1;
            for(int k=0;k<cn;k++){int pi=candidate[k],d=c.distance(previous.get(pi));if(d<best){second=best;best=d;bpi=pi;}else if(d<second)second=d;}
            if(bpi>=0&&best<=78&&(second>=999||best<second*0.82)){
                Match m=new Match(bpi,ci,best);provisional.add(m);
                if(best<distForPrev[bpi]){distForPrev[bpi]=best;bestForPrev[bpi]=ci;}
            }
        }
        for(Match m:provisional)if(bestForPrev[m.previousIndex]==m.currentIndex)out.add(m);
        return out;
    }
}
