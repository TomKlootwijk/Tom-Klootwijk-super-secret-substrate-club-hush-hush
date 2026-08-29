package org.ugts.atlas.slam.core;

import java.util.regex.Pattern;

/** Ordered verifier matching the documented 4.1 authority gates. */
public final class ProposalVerifier {
    private static final Pattern IDENTIFIER = Pattern.compile("[A-Za-z0-9._:-]{1,128}");

    public VerificationResult verify(SpatialProposal proposal) {
        byte[] canonicalHash = Hashing.sha256(proposal.canonicalBytes());
        if (!proposal.identifierValid
                || !IDENTIFIER.matcher(proposal.proposalId).matches()
                || !IDENTIFIER.matcher(proposal.entityId).matches()) {
            return reject("identifier_invalid", canonicalHash);
        }
        if (!proposal.supportOk) {
            return reject("outside_support", canonicalHash);
        }
        if (!proposal.compatibilityOk) {
            return reject("incompatible", canonicalHash);
        }
        if (!proposal.guardStatus.acceptedByDefault()) {
            return reject("guard_" + proposal.guardStatus.name().toLowerCase(), canonicalHash);
        }
        if (!finite01(proposal.confidence)
                || !finite01(proposal.confidenceFloor)
                || proposal.confidence < proposal.confidenceFloor) {
            return reject("confidence_below_floor", canonicalHash);
        }
        if (!Double.isFinite(proposal.numericError)
                || !Double.isFinite(proposal.eventMargin)
                || proposal.numericError < 0.0
                || proposal.eventMargin < 0.0
                || proposal.numericError > proposal.eventMargin) {
            return reject("numeric_error_exceeds_margin", canonicalHash);
        }
        if (!Double.isFinite(proposal.uncertainty)
                || !Double.isFinite(proposal.maxUncertainty)
                || proposal.uncertainty < 0.0
                || proposal.maxUncertainty < 0.0
                || proposal.uncertainty > proposal.maxUncertainty) {
            return reject("uncertainty_exceeds_policy", canonicalHash);
        }
        if (proposal.requiresMetric && !proposal.metricAvailable) {
            return reject("metric_unavailable", canonicalHash);
        }
        return new VerificationResult(true, "accepted", canonicalHash);
    }

    private static VerificationResult reject(String reason, byte[] hash) {
        return new VerificationResult(false, reason, hash);
    }

    private static boolean finite01(double value) {
        return Double.isFinite(value) && value >= 0.0 && value <= 1.0;
    }
}
