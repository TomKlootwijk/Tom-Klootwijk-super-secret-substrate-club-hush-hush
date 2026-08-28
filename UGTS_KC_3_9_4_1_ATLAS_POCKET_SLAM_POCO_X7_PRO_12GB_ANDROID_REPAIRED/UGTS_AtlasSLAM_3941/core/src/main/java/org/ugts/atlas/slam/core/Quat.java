package org.ugts.atlas.slam.core;

public final class Quat {
    public static final Quat IDENTITY = new Quat(1,0,0,0,false);
    public final double w,x,y,z;
    public Quat(double w,double x,double y,double z){this(w,x,y,z,true);}
    private Quat(double w,double x,double y,double z,boolean normalize){
        if(normalize){double n=Math.sqrt(w*w+x*x+y*y+z*z); if(n<1e-15){this.w=1;this.x=this.y=this.z=0;}else{this.w=w/n;this.x=x/n;this.y=y/n;this.z=z/n;}}
        else{this.w=w;this.x=x;this.y=y;this.z=z;}
    }
    public Quat multiply(Quat b){
        return new Quat(w*b.w-x*b.x-y*b.y-z*b.z,
            w*b.x+x*b.w+y*b.z-z*b.y,
            w*b.y-x*b.z+y*b.w+z*b.x,
            w*b.z+x*b.y-y*b.x+z*b.w);
    }
    public Quat conjugate(){return new Quat(w,-x,-y,-z,false);}
    public Quat inverse(){return conjugate();}
    public Vec3 rotate(Vec3 v){
        Vec3 qv=new Vec3(x,y,z); Vec3 t=qv.cross(v).scale(2.0);
        return v.add(t.scale(w)).add(qv.cross(t));
    }
    public double dot(Quat b){return w*b.w+x*b.x+y*b.y+z*b.z;}
    public double angleTo(Quat b){double d=Math.abs(dot(b)); d=Math.max(-1,Math.min(1,d)); return 2.0*Math.acos(d);}
    public static Quat fromAxisAngle(Vec3 axis,double angle){double h=angle*0.5,s=Math.sin(h);Vec3 a=axis.normalized();return new Quat(Math.cos(h),a.x*s,a.y*s,a.z*s);}
    public static Quat slerp(Quat a,Quat b,double t){
        double dot=a.dot(b); double bw=b.w,bx=b.x,by=b.y,bz=b.z;
        if(dot<0){dot=-dot;bw=-bw;bx=-bx;by=-by;bz=-bz;}
        if(dot>0.9995)return new Quat(a.w+t*(bw-a.w),a.x+t*(bx-a.x),a.y+t*(by-a.y),a.z+t*(bz-a.z));
        double th=Math.acos(Math.max(-1,Math.min(1,dot))),s=Math.sin(th);
        double u=Math.sin((1-t)*th)/s,v=Math.sin(t*th)/s;
        return new Quat(a.w*u+bw*v,a.x*u+bx*v,a.y*u+by*v,a.z*u+bz*v);
    }
    public boolean finite(){return Double.isFinite(w)&&Double.isFinite(x)&&Double.isFinite(y)&&Double.isFinite(z);}
    @Override public String toString(){return "["+w+","+x+","+y+","+z+"]";}
}
