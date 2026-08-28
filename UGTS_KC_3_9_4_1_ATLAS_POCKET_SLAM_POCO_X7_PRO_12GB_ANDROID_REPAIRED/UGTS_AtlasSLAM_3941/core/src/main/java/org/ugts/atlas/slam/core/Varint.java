package org.ugts.atlas.slam.core;

import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;

public final class Varint {
    private Varint(){}
    public static void writeUnsigned(ByteArrayOutputStream out,long v){while((v&~0x7fL)!=0){out.write((int)(v&0x7f)|0x80);v>>>=7;}out.write((int)v);}
    public static long readUnsigned(InputStream in)throws IOException{long v=0;int shift=0;while(shift<64){int b=in.read();if(b<0)throw new EOFException();v|=(long)(b&0x7f)<<shift;if((b&0x80)==0)return v;shift+=7;}throw new IOException("varint overflow");}
    public static long zigzag(int v){return ((long)v<<1)^(v>>31);}
    public static int unzigzag(long v){return (int)((v>>>1)^-(v&1));}
}
