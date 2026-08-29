package org.ugts.atlas.slam.core;
public final class Match {
    public final int previousIndex,currentIndex,distance;
    public Match(int previousIndex,int currentIndex,int distance){this.previousIndex=previousIndex;this.currentIndex=currentIndex;this.distance=distance;}
}
