package org.ugts.atlas.slam.core;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

public final class LedgerEvent {
    public final long sequence,timestampNs;
    public final String type,commitState;
    public final Map<String,String> fields;
    public LedgerEvent(long sequence,long timestampNs,String type,String commitState,Map<String,String> fields){this.sequence=sequence;this.timestampNs=timestampNs;this.type=type;this.commitState=commitState;this.fields=Collections.unmodifiableMap(new LinkedHashMap<>(fields));}
    public String toJson(){StringBuilder s=new StringBuilder();s.append('{').append("\"sequence\":").append(sequence).append(",\"timestamp_ns\":").append(timestampNs).append(",\"type\":\"").append(JsonUtil.escape(type)).append("\",\"commit_state\":\"").append(JsonUtil.escape(commitState)).append("\",\"fields\":{");boolean first=true;for(Map.Entry<String,String>e:fields.entrySet()){if(!first)s.append(',');first=false;s.append('"').append(JsonUtil.escape(e.getKey())).append("\":\"").append(JsonUtil.escape(e.getValue())).append('"');}return s.append("}}").toString();}
}
