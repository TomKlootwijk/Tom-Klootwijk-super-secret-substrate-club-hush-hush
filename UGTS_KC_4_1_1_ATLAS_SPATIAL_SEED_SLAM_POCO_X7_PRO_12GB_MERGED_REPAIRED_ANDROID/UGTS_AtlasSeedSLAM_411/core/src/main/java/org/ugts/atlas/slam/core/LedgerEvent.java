package org.ugts.atlas.slam.core;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** Ordered proposal decision with canonical proposal and pre/post state hashes. */
public final class LedgerEvent {
    private static final String ZERO_HASH = "0".repeat(64);

    public final long sequence;
    public final long timestampNs;
    public final String proposalId;
    public final String entityId;
    public final String type;
    public final String commitState;
    public final String reason;
    public final String canonicalProposalSha256;
    public final String preStateSha256;
    public final String postStateSha256;
    public final Map<String, String> fields;

    public LedgerEvent(
            long sequence,
            long timestampNs,
            String proposalId,
            String entityId,
            String type,
            String commitState,
            String reason,
            String canonicalProposalSha256,
            String preStateSha256,
            String postStateSha256,
            Map<String, String> fields) {
        this.sequence = sequence;
        this.timestampNs = timestampNs;
        this.proposalId = value(proposalId, "proposal:" + sequence);
        this.entityId = value(entityId, "session");
        this.type = value(type, "unknown");
        this.commitState = value(commitState, "rejected");
        this.reason = value(reason, "unspecified");
        this.canonicalProposalSha256 = hash(canonicalProposalSha256);
        this.preStateSha256 = hash(preStateSha256);
        this.postStateSha256 = hash(postStateSha256);
        this.fields = Collections.unmodifiableMap(new LinkedHashMap<>(fields));
    }

    /** Compatibility shape for the previous 3.9.4.1 event record. */
    public LedgerEvent(
            long sequence,
            long timestampNs,
            String type,
            String commitState,
            Map<String, String> fields) {
        this(
                sequence,
                timestampNs,
                "legacy:" + sequence,
                "session",
                type,
                commitState,
                "accepted".equals(commitState) ? "accepted" : commitState,
                ZERO_HASH,
                ZERO_HASH,
                ZERO_HASH,
                fields);
    }

    public String toJson() {
        StringBuilder text = new StringBuilder()
                .append('{')
                .append("\"sequence\":").append(sequence)
                .append(",\"timestamp_ns\":").append(timestampNs)
                .append(",\"proposal_id\":\"").append(JsonUtil.escape(proposalId)).append('"')
                .append(",\"entity_id\":\"").append(JsonUtil.escape(entityId)).append('"')
                .append(",\"type\":\"").append(JsonUtil.escape(type)).append('"')
                .append(",\"commit_state\":\"").append(JsonUtil.escape(commitState)).append('"')
                .append(",\"reason\":\"").append(JsonUtil.escape(reason)).append('"')
                .append(",\"canonical_proposal_sha256\":\"")
                .append(canonicalProposalSha256).append('"')
                .append(",\"pre_state_sha256\":\"").append(preStateSha256).append('"')
                .append(",\"post_state_sha256\":\"").append(postStateSha256).append('"')
                .append(",\"fields\":{");
        boolean first = true;
        for (Map.Entry<String, String> item : fields.entrySet()) {
            if (!first) {
                text.append(',');
            }
            first = false;
            text.append('"').append(JsonUtil.escape(item.getKey())).append("\":\"")
                    .append(JsonUtil.escape(item.getValue())).append('"');
        }
        return text.append("}}").toString();
    }

    private static String value(String input, String fallback) {
        return input == null || input.isEmpty() ? fallback : input;
    }

    private static String hash(String input) {
        if (input != null && input.matches("[0-9a-fA-F]{64}")) {
            return input.toLowerCase();
        }
        return ZERO_HASH;
    }
}
