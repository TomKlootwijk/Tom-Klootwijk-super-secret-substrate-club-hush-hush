package org.ugts.atlas.slam.core;

/** Result of the ordered 4.1 verifier gates. */
public final class VerificationResult {
    public final boolean accepted;
    public final String reason;
    public final byte[] canonicalProposalHash;

    VerificationResult(boolean accepted, String reason, byte[] canonicalProposalHash) {
        this.accepted = accepted;
        this.reason = reason;
        this.canonicalProposalHash = canonicalProposalHash;
    }
}
