package org.ugts.atlas.slam.core;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.zip.Deflater;
import java.util.zip.DeflaterOutputStream;
import java.util.zip.InflaterInputStream;

/** Deterministic quantized/delta/varint codec used inside .ugtsscan containers. */
public final class UgtsScanCodec {
    private static final byte[] MAGIC={'U','G','3','D'};
    public static byte[] encode(List<VoxelMap.Cell> cells,double voxelSize)throws IOException{
        ByteArrayOutputStream raw=new ByteArrayOutputStream(Math.max(256,cells.size()*8));int px=0,py=0,pz=0;
        Varint.writeUnsigned(raw,cells.size());
        for(VoxelMap.Cell c:cells){Varint.writeUnsigned(raw,Varint.zigzag(c.qx-px));Varint.writeUnsigned(raw,Varint.zigzag(c.qy-py));Varint.writeUnsigned(raw,Varint.zigzag(c.qz-pz));px=c.qx;py=c.qy;pz=c.qz;raw.write(c.intensity());raw.write((int)Math.round(c.confidence()*255));Varint.writeUnsigned(raw,c.observations());}
        ByteArrayOutputStream out=new ByteArrayOutputStream();DataOutputStream data=new DataOutputStream(out);data.write(MAGIC);data.writeByte(1);data.writeDouble(voxelSize);data.flush();
        Deflater def=new Deflater(3,false);try(DeflaterOutputStream z=new DeflaterOutputStream(out,def,16384,true)){z.write(raw.toByteArray());}return out.toByteArray();
    }
    public static Decoded decode(byte[] bytes)throws IOException{
        DataInputStream head=new DataInputStream(new ByteArrayInputStream(bytes));for(byte m:MAGIC)if(head.readByte()!=m)throw new IOException("bad magic");int version=head.readUnsignedByte();if(version!=1)throw new IOException("version");double voxel=head.readDouble();ArrayList<int[]> q=new ArrayList<>();
        try(InflaterInputStream in=new InflaterInputStream(head)){long count=Varint.readUnsigned(in);if(count>10_000_000)throw new IOException("count");int x=0,y=0,z=0;for(long i=0;i<count;i++){x+=Varint.unzigzag(Varint.readUnsigned(in));y+=Varint.unzigzag(Varint.readUnsigned(in));z+=Varint.unzigzag(Varint.readUnsigned(in));int intensity=in.read(),confidence=in.read();if(intensity<0||confidence<0)throw new IOException("truncated");int obs=(int)Varint.readUnsigned(in);q.add(new int[]{x,y,z,intensity,confidence,obs});}}return new Decoded(voxel,q);
    }
    public static final class Decoded {public final double voxelSize;public final List<int[]> records;Decoded(double v,List<int[]>r){voxelSize=v;records=r;}}
}
