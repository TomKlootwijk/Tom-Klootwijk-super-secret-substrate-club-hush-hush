import json
from pathlib import Path

import cv2
import numpy as np


VIDEO = Path(r"C:\Users\Tom\Videos\KasiaDansGedicht\sam_2353410928515192.mp4")
GAPS = (1, 5, 12, 25)
WIDTH = 640
FB_LIMIT_PX = 1.5
H_RANSAC_PX = 3.0
F_RANSAC_PX = 1.5


def load_gray_frames(path: Path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    frames: list[np.ndarray] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        height = round(frame.shape[0] * WIDTH / frame.shape[1])
        frame = cv2.resize(frame, (WIDTH, height), interpolation=cv2.INTER_AREA)
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    cap.release()
    if not frames:
        raise RuntimeError(f"No frames decoded from {path}")
    return frames


def summarize_gap(frames: list[np.ndarray], gap: int) -> dict:
    last_start = len(frames) - gap - 1
    starts = np.unique(np.linspace(0, last_start, num=min(24, last_start + 1), dtype=int))
    initial_total = 0
    retained_total = 0
    homography_total = 0
    homography_inliers = 0
    fundamental_total = 0
    fundamental_inliers = 0
    flow_magnitudes: list[float] = []
    h_residuals: list[float] = []

    lk_params = dict(
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )

    for start in starts:
        first = frames[int(start)]
        second = frames[int(start + gap)]
        points0 = cv2.goodFeaturesToTrack(
            first,
            maxCorners=800,
            qualityLevel=0.01,
            minDistance=7,
            blockSize=7,
        )
        if points0 is None or len(points0) < 8:
            continue

        points1, status1, _ = cv2.calcOpticalFlowPyrLK(first, second, points0, None, **lk_params)
        points0_back, status2, _ = cv2.calcOpticalFlowPyrLK(second, first, points1, None, **lk_params)
        forward = points1.reshape(-1, 2)
        original = points0.reshape(-1, 2)
        backward = points0_back.reshape(-1, 2)
        valid = (
            status1.reshape(-1).astype(bool)
            & status2.reshape(-1).astype(bool)
            & (np.linalg.norm(backward - original, axis=1) <= FB_LIMIT_PX)
        )
        p0 = original[valid]
        p1 = forward[valid]

        initial_total += len(original)
        retained_total += len(p0)
        if len(p0) < 8:
            continue

        flow_magnitudes.extend(np.linalg.norm(p1 - p0, axis=1).tolist())

        homography, h_mask = cv2.findHomography(p0, p1, cv2.RANSAC, H_RANSAC_PX)
        if homography is not None and h_mask is not None:
            projected = cv2.perspectiveTransform(p0.reshape(-1, 1, 2), homography).reshape(-1, 2)
            residual = np.linalg.norm(projected - p1, axis=1)
            h_residuals.extend(residual.tolist())
            homography_total += len(p0)
            homography_inliers += int(h_mask.reshape(-1).sum())

        fundamental, f_mask = cv2.findFundamentalMat(
            p0,
            p1,
            cv2.FM_RANSAC,
            F_RANSAC_PX,
            0.99,
        )
        if fundamental is not None and f_mask is not None:
            fundamental_total += len(p0)
            fundamental_inliers += int(f_mask.reshape(-1).sum())

    return {
        "gap_frames": gap,
        "pair_count": int(len(starts)),
        "initial_features": initial_total,
        "forward_backward_retained_fraction": retained_total / initial_total if initial_total else None,
        "median_flow_px": float(np.median(flow_magnitudes)) if flow_magnitudes else None,
        "homography_inlier_fraction": homography_inliers / homography_total if homography_total else None,
        "homography_residual_gt_3px_fraction": float(np.mean(np.asarray(h_residuals) > 3.0)) if h_residuals else None,
        "median_homography_residual_px": float(np.median(h_residuals)) if h_residuals else None,
        "fundamental_inlier_fraction": fundamental_inliers / fundamental_total if fundamental_total else None,
    }


def main() -> None:
    frames = load_gray_frames(VIDEO)
    payload = {
        "video": str(VIDEO),
        "decoded_frames": len(frames),
        "analysis_resolution": [int(frames[0].shape[1]), int(frames[0].shape[0])],
        "settings": {
            "pair_sampling": "up to 24 uniformly spaced starts per gap",
            "shi_tomasi_max_corners": 800,
            "shi_tomasi_quality": 0.01,
            "shi_tomasi_min_distance_px": 7,
            "lk_window": [21, 21],
            "lk_pyramid_levels": 4,
            "forward_backward_limit_px": FB_LIMIT_PX,
            "homography_ransac_px": H_RANSAC_PX,
            "fundamental_ransac_px": F_RANSAC_PX,
        },
        "gaps": [summarize_gap(frames, gap) for gap in GAPS],
        "interpretation_limit": (
            "Tracks are unsegmented and mix people with background. These values diagnose motion/"
            "projective inconsistency only; they are not camera calibration, metric depth, or a person mesh."
        ),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
