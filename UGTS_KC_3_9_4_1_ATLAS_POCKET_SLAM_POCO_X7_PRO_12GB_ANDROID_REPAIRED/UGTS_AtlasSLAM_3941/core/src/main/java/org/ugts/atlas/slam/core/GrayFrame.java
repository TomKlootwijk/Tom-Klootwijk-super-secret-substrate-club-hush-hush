package org.ugts.atlas.slam.core;

import java.util.Arrays;

public final class GrayFrame {
    public final int width,height;
    public final long timestampNs;
    public final byte[] pixels;
    public GrayFrame(int width,int height,long timestampNs,byte[] pixels){
        if(width<=0||height<=0||pixels==null||pixels.length!=width*height)throw new IllegalArgumentException("invalid gray frame");
        this.width=width;this.height=height;this.timestampNs=timestampNs;this.pixels=pixels;
    }
    public int u8(int x,int y){return pixels[y*width+x]&255;}
    public double sample(double x,double y){
        if(x<0||y<0||x>=width-1||y>=height-1)return 0;
        int x0=(int)x,y0=(int)y;double ax=x-x0,ay=y-y0;
        double a=u8(x0,y0)*(1-ax)+u8(x0+1,y0)*ax;
        double b=u8(x0,y0+1)*(1-ax)+u8(x0+1,y0+1)*ax;
        return a*(1-ay)+b*ay;
    }
    public int gradientL1(int x,int y){return Math.abs(u8(x+1,y)-u8(x-1,y))+Math.abs(u8(x,y+1)-u8(x,y-1));}
    public GrayFrame copy(){return new GrayFrame(width,height,timestampNs,Arrays.copyOf(pixels,pixels.length));}
}
