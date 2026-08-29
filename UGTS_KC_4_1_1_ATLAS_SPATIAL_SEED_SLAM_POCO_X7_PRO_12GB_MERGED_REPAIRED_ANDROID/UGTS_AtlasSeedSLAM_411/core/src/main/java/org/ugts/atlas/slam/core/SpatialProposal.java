package org.ugts.atlas.slam.core;

import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.Map;
import java.util.TreeMap;

/** Proposal-only observation record. The verifier owns authoritative acceptance. */
public final class SpatialProposal {
    public static final int TAG_SYNTHETIC = 1 << 31;

    public final String proposalId;
    public final String entityId;
    public final long timestampNs;
    public final String type;
    public final boolean identifierValid;
    public final boolean supportOk;
    public final boolean compatibilityOk;
    public final GuardStatus guardStatus;
    public final double confidence;
    public final double confidenceFloor;
    public final double numericError;
    public final double eventMargin;
    public final double uncertainty;
    public final double maxUncertainty;
    public final boolean requiresMetric;
    public final boolean metricAvailable;
    public final int tags;
    public final Map<String, String> payload;

    public SpatialProposal(
            String proposalId,
            String entityId,
            long timestampNs,
            String type,
            boolean identifierValid,
            boolean supportOk,
            boolean compatibilityOk,
            GuardStatus guardStatus,
            double confidence,
            double confidenceFloor,
            double numericError,
            double eventMargin,
            double uncertainty,
            double maxUncertainty,
            boolean requiresMetric,
            boolean metricAvailable,
            int tags,
            Map<String, String> payload) {
        this.proposalId = proposalId == null ? "" : proposalId;
        this.entityId = entityId == null ? "" : entityId;
        this.timestampNs = timestampNs;
        this.type = type == null ? "unknown" : type;
        this.identifierValid = identifierValid;
        this.supportOk = supportOk;
        this.compatibilityOk = compatibilityOk;
        this.guardStatus = guardStatus == null ? GuardStatus.UNKNOWN : guardStatus;
        this.confidence = confidence;
        this.confidenceFloor = confidenceFloor;
        this.numericError = numericError;
        this.eventMargin = eventMargin;
        this.uncertainty = uncertainty;
        this.maxUncertainty = maxUncertainty;
        this.requiresMetric = requiresMetric;
        this.metricAvailable = metricAvailable;
        this.tags = tags;
        this.payload = Collections.unmodifiableMap(new TreeMap<>(payload));
    }

    public byte[] canonicalBytes() {
        StringBuilder value = new StringBuilder(512)
                .append("proposal_id=").append(proposalId).append('\n')
                .append("entity_id=").append(entityId).append('\n')
                .append("timestamp_ns=").append(timestampNs).append('\n')
                .append("type=").append(type).append('\n')
                .append("identifier_valid=").append(identifierValid).append('\n')
                .append("support_ok=").append(supportOk).append('\n')
                .append("compatibility_ok=").append(compatibilityOk).append('\n')
                .append("guard_status=").append(guardStatus.name()).append('\n')
                .append("confidence=").append(Double.toHexString(confidence)).append('\n')
                .append("confidence_floor=").append(Double.toHexString(confidenceFloor)).append('\n')
                .append("numeric_error=").append(Double.toHexString(numericError)).append('\n')
                .append("event_margin=").append(Double.toHexString(eventMargin)).append('\n')
                .append("uncertainty=").append(Double.toHexString(uncertainty)).append('\n')
                .append("max_uncertainty=").append(Double.toHexString(maxUncertainty)).append('\n')
                .append("requires_metric=").append(requiresMetric).append('\n')
                .append("metric_available=").append(metricAvailable).append('\n')
                .append("tags=").append(Integer.toUnsignedString(tags)).append('\n');
        for (Map.Entry<String, String> item : payload.entrySet()) {
            value.append("payload.").append(item.getKey()).append('=')
                    .append(item.getValue()).append('\n');
        }
        return value.toString().getBytes(StandardCharsets.UTF_8);
    }

    public boolean synthetic() {
        return (tags & TAG_SYNTHETIC) != 0;
    }
}
