package org.ugts.atlas.slam.core;

import java.util.Locale;

public final class Vec3 {
    public static final Vec3 ZERO = new Vec3(0.0, 0.0, 0.0);
    public final double x, y, z;
    public Vec3(double x, double y, double z) { this.x=x; this.y=y; this.z=z; }
    public Vec3 add(Vec3 b) { return new Vec3(x+b.x, y+b.y, z+b.z); }
    public Vec3 sub(Vec3 b) { return new Vec3(x-b.x, y-b.y, z-b.z); }
    public Vec3 scale(double s) { return new Vec3(x*s, y*s, z*s); }
    public double dot(Vec3 b) { return x*b.x+y*b.y+z*b.z; }
    public Vec3 cross(Vec3 b) { return new Vec3(y*b.z-z*b.y, z*b.x-x*b.z, x*b.y-y*b.x); }
    public double normSquared() { return dot(this); }
    public double norm() { return Math.sqrt(normSquared()); }
    public Vec3 normalized() { double n=norm(); return n<1e-12 ? ZERO : scale(1.0/n); }
    public double distance(Vec3 b) { return sub(b).norm(); }
    public boolean finite() { return Double.isFinite(x)&&Double.isFinite(y)&&Double.isFinite(z); }
    public static Vec3 lerp(Vec3 a, Vec3 b, double t) { return a.scale(1-t).add(b.scale(t)); }
    public static double clamp(double v,double lo,double hi){return Math.max(lo,Math.min(hi,v));}
    @Override public boolean equals(Object o){
        if(!(o instanceof Vec3)) return false; Vec3 b=(Vec3)o;
        return Double.doubleToLongBits(x)==Double.doubleToLongBits(b.x)&&Double.doubleToLongBits(y)==Double.doubleToLongBits(b.y)&&Double.doubleToLongBits(z)==Double.doubleToLongBits(b.z);
    }
    @Override public int hashCode(){ long h=Double.doubleToLongBits(x); h=31*h+Double.doubleToLongBits(y); h=31*h+Double.doubleToLongBits(z); return (int)(h^(h>>>32)); }
    @Override public String toString(){return String.format(Locale.ROOT,"(%.6f,%.6f,%.6f)",x,y,z);}
}
