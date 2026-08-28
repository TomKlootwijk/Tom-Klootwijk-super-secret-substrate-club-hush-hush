package org.ugts.atlas.slam.core;

import java.util.Collections;
import java.util.List;

public final class SessionData {
    public final String sessionId,scaleState,cameraSource;
    public final long startedNs,endedNs,frames;
    public final double metricScale,voxelSize;
    public final boolean cameraCalibrated;
    public final List<VoxelMap.Cell> cells;
    public final List<Keyframe> keyframes;
    public final List<LedgerEvent> events;
    public SessionData(String sessionId,String scaleState,String cameraSource,long startedNs,long endedNs,long frames,double metricScale,double voxelSize,boolean cameraCalibrated,List<VoxelMap.Cell> cells,List<Keyframe> keyframes,List<LedgerEvent> events){this.sessionId=sessionId;this.scaleState=scaleState;this.cameraSource=cameraSource;this.startedNs=startedNs;this.endedNs=endedNs;this.frames=frames;this.metricScale=metricScale;this.voxelSize=voxelSize;this.cameraCalibrated=cameraCalibrated;this.cells=Collections.unmodifiableList(cells);this.keyframes=Collections.unmodifiableList(keyframes);this.events=Collections.unmodifiableList(events);}
}
