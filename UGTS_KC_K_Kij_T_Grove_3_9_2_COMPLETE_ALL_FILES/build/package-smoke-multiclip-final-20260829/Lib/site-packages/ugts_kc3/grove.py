"""K-Kij-T / Grove 3.9.2 deterministic tuning contract."""
from dataclasses import dataclass

@dataclass(frozen=True)
class GroveTuning:
    profile: str
    juice_intensity: float
    bloom: float
    particle_budget: int
    post_processing: bool
    target_fps: int

def choose_grove_tuning(model: str = "", gpu: str = "", ram_mb: int = 4096, refresh_hz: int = 60) -> GroveTuning:
    text = f"{model} {gpu}".lower()
    poco = "poco x7 pro" in text or "2412dpc0" in text
    mali = "mali-g720" in text or "mali-g710" in text or "mali-g715" in text
    if poco and mali:
        return GroveTuning("grove_g720_mc7_120", 1.0, 0.70, 384, True, 120 if refresh_hz >= 120 else 90)
    if mali:
        return GroveTuning("grove_mali_high_90", 0.90, 0.60, 256, True, min(90, refresh_hz))
    if ram_mb >= 6144:
        return GroveTuning("grove_android_high_90", 0.85, 0.55, 220, True, min(90, refresh_hz))
    if ram_mb >= 3072:
        return GroveTuning("grove_balanced_60", 0.72, 0.42, 128, True, min(60, refresh_hz))
    return GroveTuning("grove_compat_60", 0.48, 0.20, 48, False, min(60, refresh_hz))
