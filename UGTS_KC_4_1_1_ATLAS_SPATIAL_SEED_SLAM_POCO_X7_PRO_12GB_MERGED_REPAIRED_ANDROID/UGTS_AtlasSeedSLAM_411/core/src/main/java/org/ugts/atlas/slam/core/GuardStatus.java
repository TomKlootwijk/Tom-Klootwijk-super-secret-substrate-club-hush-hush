package org.ugts.atlas.slam.core;

/** Explicit relation/guard classes carried by proposals. */
public enum GuardStatus {
    CROSSING,
    TOUCH,
    TANGENCY,
    COINCIDENT,
    UNKNOWN;

    public boolean acceptedByDefault() {
        return this == CROSSING || this == TOUCH;
    }
}
