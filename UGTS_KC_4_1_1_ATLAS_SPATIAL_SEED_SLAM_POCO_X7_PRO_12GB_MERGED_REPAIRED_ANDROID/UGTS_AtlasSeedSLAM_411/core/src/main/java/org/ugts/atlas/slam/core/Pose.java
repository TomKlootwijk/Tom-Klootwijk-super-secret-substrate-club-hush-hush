package org.ugts.atlas.slam.core;

public final class Pose {
    public static final Pose IDENTITY = new Pose(Quat.IDENTITY, Vec3.ZERO);
    /** worldFromCamera orientation and camera centre in world coordinates. */
    public final Quat orientation;
    public final Vec3 position;
    public Pose(Quat orientation, Vec3 position){this.orientation=orientation;this.position=position;}
    public Vec3 cameraToWorld(Vec3 p){return position.add(orientation.rotate(p));}
    public Vec3 worldToCamera(Vec3 p){return orientation.conjugate().rotate(p.sub(position));}
    public Vec3 directionCameraToWorld(Vec3 d){return orientation.rotate(d);}
    public Pose scaled(double s){return new Pose(orientation,position.scale(s));}
    public Pose withPosition(Vec3 p){return new Pose(orientation,p);}
    public double translationDistance(Pose b){return position.distance(b.position);}
    public double rotationDistance(Pose b){return orientation.angleTo(b.orientation);}
}
