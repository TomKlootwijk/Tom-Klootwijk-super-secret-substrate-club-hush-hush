package org.ugts.atlas.slam.core;

import java.util.Locale;

public final class JsonUtil {
    private JsonUtil(){}
    public static String escape(String v){if(v==null)return "";StringBuilder s=new StringBuilder(v.length()+8);for(int i=0;i<v.length();i++){char c=v.charAt(i);switch(c){case '"':s.append("\\\"");break;case '\\':s.append("\\\\");break;case '\n':s.append("\\n");break;case '\r':s.append("\\r");break;case '\t':s.append("\\t");break;default:if(c<32)s.append(String.format(Locale.ROOT,"\\u%04x",(int)c));else s.append(c);}}return s.toString();}
    public static String finite(double v){return Double.isFinite(v)?String.format(Locale.ROOT,"%.9g",v):"null";}
}
