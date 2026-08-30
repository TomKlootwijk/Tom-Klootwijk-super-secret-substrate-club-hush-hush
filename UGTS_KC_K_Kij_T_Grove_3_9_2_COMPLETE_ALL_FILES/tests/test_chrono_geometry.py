import dataclasses
import hashlib
import json
import math
import unittest

import cv2
import numpy as np

from ugts_kc3.chrono_geometry import (
    ChronoGeometryConfig,
    FrameAddress,
    IntrinsicsCandidate,
    estimate_two_view_geometry,
    operator_provenance_registry,
    propose_residual_motion_components,
    sampson_residuals,
    symmetric_transfer_residuals,
    track_gftt_klt,
)


def _rotation_vector(vector):
    return cv2.Rodrigues(np.asarray(vector, dtype=np.float64))[0]


def _project(points, rotation, translation, intrinsic):
    camera = (rotation @ points.T).T + translation
    homogeneous = (intrinsic @ camera.T).T
    return homogeneous[:, :2] / homogeneous[:, 2, None]


class ChronoGeometryTests(unittest.TestCase):
    def setUp(self):
        self.source_hash = hashlib.sha256(b"exact-source-video").hexdigest()
        self.first = FrameAddress(
            self.source_hash,
            source_frame_index=10,
            source_pts=1000,
            time_base_num=1,
            time_base_den=30_000,
            width=640,
            height=480,
        )
        self.second = FrameAddress(
            self.source_hash,
            source_frame_index=11,
            source_pts=2001,
            time_base_num=1,
            time_base_den=30_000,
            width=640,
            height=480,
        )
        self.intrinsic = np.array(
            ((820.0, 0.0, 320.0), (0.0, 815.0, 240.0), (0.0, 0.0, 1.0)),
            dtype=np.float64,
        )
        self.candidate = IntrinsicsCandidate(
            "known-synthetic-K-candidate",
            fx=820.0,
            fy=815.0,
            cx=320.0,
            cy=240.0,
            origin="SYNTHETIC_TEST_CANDIDATE_NOT_RUNTIME_CALIBRATION",
        )
        self.config = ChronoGeometryConfig(
            min_correspondences=16,
            min_fundamental_inliers=12,
            ransac_fundamental_threshold_pixels=0.75,
            ransac_homography_threshold_pixels=1.0,
            min_parallax_degrees=0.5,
            max_median_reprojection_pixels=1.0,
        )

    def _nonplanar_fixture(self, *, translation=(0.65, 0.025, 0.04), noise=0.03):
        rng = np.random.default_rng(392)
        points = np.column_stack(
            (
                rng.uniform(-0.75, 0.75, 120),
                rng.uniform(-0.75, 0.75, 120),
                rng.uniform(4.0, 10.0, 120),
            )
        )
        rotation = _rotation_vector((0.025, -0.075, 0.018))
        translation_array = np.asarray(translation, dtype=np.float64)
        image0 = _project(points, np.eye(3), np.zeros(3), self.intrinsic)
        image1 = _project(points, rotation, translation_array, self.intrinsic)
        if noise:
            image0 += rng.normal(0.0, noise, image0.shape)
            image1 += rng.normal(0.0, noise, image1.shape)
        return points, rotation, translation_array, image0, image1

    def test_known_two_view_recovers_relative_geometry_up_to_gauge(self):
        points, expected_rotation, expected_translation, image0, image1 = (
            self._nonplanar_fixture()
        )
        track_ids = [f"synthetic-track-{index:03d}" for index in range(len(points))]
        report = estimate_two_view_geometry(
            self.first,
            self.second,
            image0,
            image1,
            intrinsics_candidates=[self.candidate],
            track_ids=track_ids,
            config=self.config,
        )
        self.assertEqual(report["state"], "BOUNDED_RELATIVE_PROJECTIVE_HYPOTHESES")
        json.dumps(report, allow_nan=False)
        self.assertEqual(report["physical_geometry_state"], "UNBOUNDED_UNKNOWN")
        self.assertEqual(report["metric_scale_state"], "UNKNOWN_MONOCULAR_GAUGE")
        self.assertEqual(report["cross_time_faces"], [])
        self.assertEqual(
            report["intrinsics_selection_state"],
            "BOUNDED_JOINT_HYPOTHESES_NO_CALIBRATION_BRANCH_PROMOTED",
        )
        branch = report["intrinsics_branches"][0]
        self.assertEqual(branch["state"], "BOUNDED_RELATIVE_POSE_HYPOTHESIS")
        self.assertEqual(
            branch["calibration_state"],
            "CANDIDATE_UNVERIFIED_NOT_PHYSICAL_TRUTH",
        )
        selected = branch["four_pose_hypotheses"][
            branch["selected_pose_hypothesis_index"]
        ]
        estimated_rotation = np.asarray(selected["rotation"])
        rotation_delta = estimated_rotation @ expected_rotation.T
        rotation_error = math.degrees(
            math.acos(np.clip((np.trace(rotation_delta) - 1.0) * 0.5, -1.0, 1.0))
        )
        self.assertLess(rotation_error, 0.35)
        estimated_translation = np.asarray(
            selected["translation_direction_unit_gauge"]
        )
        expected_direction = expected_translation / np.linalg.norm(expected_translation)
        self.assertGreater(float(np.dot(estimated_translation, expected_direction)), 0.995)
        self.assertGreater(len(branch["relative_point_hypotheses"]), 100)

        expected_by_track = {
            track_id: point / np.linalg.norm(expected_translation)
            for track_id, point in zip(track_ids, points)
        }
        relative_errors = []
        for point in branch["relative_point_hypotheses"]:
            expected = expected_by_track[point["track_id"]]
            estimated = np.asarray(point["position_unit_baseline_relative_gauge"])
            relative_errors.append(np.linalg.norm(estimated - expected) / np.linalg.norm(expected))
        self.assertLess(float(np.median(relative_errors)), 0.025)

        repeated = estimate_two_view_geometry(
            self.first,
            self.second,
            image0[::-1],
            image1[::-1],
            intrinsics_candidates=[self.candidate],
            track_ids=track_ids[::-1],
            config=self.config,
        )
        self.assertEqual(report["report_sha256"], repeated["report_sha256"])

    def test_pure_rotation_fails_closed_as_homography_degeneracy(self):
        rng = np.random.default_rng(12)
        points = np.column_stack(
            (
                rng.uniform(-0.75, 0.75, 80),
                rng.uniform(-0.75, 0.75, 80),
                rng.uniform(4.0, 9.0, 80),
            )
        )
        rotation = _rotation_vector((0.03, -0.11, 0.01))
        image0 = _project(points, np.eye(3), np.zeros(3), self.intrinsic)
        image1 = _project(points, rotation, np.zeros(3), self.intrinsic)
        report = estimate_two_view_geometry(
            self.first,
            self.second,
            image0,
            image1,
            intrinsics_candidates=[self.candidate],
            config=self.config,
        )
        self.assertEqual(report["state"], "REJECTED_UNBOUNDED_UNKNOWN")
        self.assertIn(
            "PLANAR_OR_PURE_ROTATION_HOMOGRAPHY_DOMINANT",
            report["rejection_reasons"],
        )
        self.assertEqual(report["physical_geometry_state"], "UNBOUNDED_UNKNOWN")

    def test_low_parallax_fails_closed_at_pose_gate(self):
        _, _, _, image0, image1 = self._nonplanar_fixture(
            translation=(0.001, 0.0, 0.0), noise=0.0
        )
        strict_homography = dataclasses.replace(
            self.config,
            ransac_fundamental_threshold_pixels=0.05,
            ransac_homography_threshold_pixels=1.0e-5,
            min_parallax_degrees=0.5,
        )
        report = estimate_two_view_geometry(
            self.first,
            self.second,
            image0,
            image1,
            intrinsics_candidates=[self.candidate],
            config=strict_homography,
        )
        self.assertEqual(report["state"], "REJECTED_UNBOUNDED_UNKNOWN")
        self.assertEqual(report["rejection_reasons"], ["ALL_INTRINSICS_BRANCHES_REJECTED"])
        self.assertIn("LOW_PARALLAX", report["intrinsics_branches"][0]["rejection_reasons"])
        self.assertEqual(report["intrinsics_branches"][0]["relative_point_hypotheses"], [])

    def test_collinear_correspondences_fail_closed(self):
        x = np.linspace(40.0, 590.0, 40)
        image0 = np.column_stack((x, 0.35 * x + 30.0))
        image1 = np.column_stack((x + 8.0, 0.35 * x + 33.0))
        report = estimate_two_view_geometry(
            self.first,
            self.second,
            image0,
            image1,
            intrinsics_candidates=[self.candidate],
            config=self.config,
        )
        self.assertEqual(report["state"], "REJECTED_UNBOUNDED_UNKNOWN")
        self.assertTrue(
            {"FUNDAMENTAL_ESTIMATION_FAILED", "FUNDAMENTAL_DESIGN_RANK_DEGENERATE"}
            & set(report["rejection_reasons"])
        )

    def test_explicit_residual_equations_are_zero_on_exact_constraints(self):
        points, rotation, translation, image0, image1 = self._nonplanar_fixture(noise=0.0)
        del points
        cross_translation = np.array(
            (
                (0.0, -translation[2], translation[1]),
                (translation[2], 0.0, -translation[0]),
                (-translation[1], translation[0], 0.0),
            )
        )
        inverse_k = np.linalg.inv(self.intrinsic)
        fundamental = inverse_k.T @ cross_translation @ rotation @ inverse_k
        self.assertLess(float(np.max(sampson_residuals(fundamental, image0, image1))), 1.0e-20)

        square = np.array(((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)))
        homography = np.array(((1.1, 0.1, 4.0), (-0.03, 0.9, 2.0), (0.001, 0.0, 1.0)))
        mapped_h = (homography @ np.column_stack((square, np.ones(4))).T).T
        mapped = mapped_h[:, :2] / mapped_h[:, 2, None]
        self.assertLess(
            float(np.max(symmetric_transfer_residuals(homography, square, mapped))),
            1.0e-24,
        )

    def test_gftt_klt_tracks_bind_exact_pts_and_forward_backward_gate(self):
        height, width = 240, 320
        first_image = np.zeros((height, width), dtype=np.uint8)
        for y in range(30, 220, 30):
            for x in range(30, 300, 30):
                cv2.rectangle(first_image, (x - 3, y - 3), (x + 3, y + 3), 255, -1)
        transform = np.float32(((1.0, 0.0, 4.0), (0.0, 1.0, 3.0)))
        second_image = cv2.warpAffine(first_image, transform, (width, height))
        first_address = dataclasses.replace(self.first, width=width, height=height)
        second_address = dataclasses.replace(self.second, width=width, height=height)
        config = dataclasses.replace(
            self.config, min_correspondences=8, min_fundamental_inliers=8
        )
        report = track_gftt_klt(
            first_image,
            second_image,
            first_address,
            second_address,
            config=config,
        )
        self.assertEqual(report["state"], "BOUNDED_TRACK_SUPPORT")
        self.assertGreater(report["correspondence_count"], 30)
        flow = np.array(
            [
                np.asarray(item["to_pixel"]) - np.asarray(item["from_pixel"])
                for item in report["correspondences"]
            ]
        )
        np.testing.assert_allclose(np.median(flow, axis=0), (4.0, 3.0), atol=0.05)
        self.assertEqual(report["frames"][0]["source_pts"], 1000)
        self.assertEqual(report["frames"][1]["source_pts"], 2001)
        self.assertEqual(report["cross_time_faces"], [])

    def test_motion_components_are_nonsemantic_lineage_proposals(self):
        points0 = np.array(
            (
                (10, 10), (13, 12), (15, 8),
                (100, 100), (104, 101), (101, 105),
                (250, 200),
            ),
            dtype=np.float64,
        )
        points1 = points0 + np.array(
            ((5, 0), (5.2, 0.1), (4.9, -0.1), (-3, 4), (-3.1, 4), (-2.9, 4.1), (20, 20))
        )
        config = dataclasses.replace(
            self.config,
            motion_component_spatial_radius_pixels=12.0,
            motion_component_flow_radius_pixels=1.0,
            motion_component_min_support=3,
        )
        report = propose_residual_motion_components(
            points0,
            points1,
            np.ones(len(points0), dtype=bool),
            self.first,
            self.second,
            config=config,
        )
        self.assertEqual(len(report["components"]), 2)
        self.assertEqual(len(report["ungrouped_residual_track_ids"]), 1)
        for component in report["components"]:
            self.assertEqual(
                component["semantic_identity_state"], "UNKNOWN_NOT_INFERRED"
            )
            self.assertEqual(
                component["temporal_relation"],
                "LINEAGE_ONLY_NO_CROSS_TIME_SURFACE",
            )

    def test_provenance_registry_contains_only_nonlearned_operators(self):
        registry = operator_provenance_registry()
        self.assertEqual(registry["coordinate_chart"], "SOURCE_RASTER_PIXELS_PRIOR_TO_LOG_POLAR_RESAMPLING")
        self.assertEqual(len(registry["registry_sha256"]), 64)
        self.assertTrue(registry["operators"])
        self.assertTrue(
            all(
                not operator["learned_or_generative"]
                for operator in registry["operators"].values()
            )
        )

    def test_frame_pair_rejects_source_hash_or_pts_substitution(self):
        wrong_source = dataclasses.replace(
            self.second, source_sha256=hashlib.sha256(b"other").hexdigest()
        )
        with self.assertRaisesRegex(ValueError, "same exact source"):
            estimate_two_view_geometry(
                self.first,
                wrong_source,
                np.zeros((16, 2)),
                np.zeros((16, 2)),
            )
        float_pts = dataclasses.replace(self.second, source_pts=2001.0)
        with self.assertRaisesRegex(ValueError, "exact integers"):
            float_pts.validate()


if __name__ == "__main__":
    unittest.main()
