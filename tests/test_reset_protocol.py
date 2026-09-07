"""Synthetic protocol and acceptance tests, never simulator evidence."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import reset_protocol as protocol


class Message:
    def __init__(self, **kwargs):
        vars(self).update(kwargs)

    def to_msgpack(self):
        return vars(self)


def vector(x=0, y=0, z=0):
    return Message(x_val=x, y_val=y, z_val=z)


def quaternion(x=0, y=0, z=0, w=1):
    return Message(x_val=x, y_val=y, z_val=z, w_val=w)


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, kind, **values):
        self.events.append((kind, values))
        return len(self.events)


class Runtime:
    def __init__(self):
        self.rec = Recorder()
        self.attempt_id = "synthetic-attempt"

    def patch(self, obj, name, hook):
        original = getattr(obj, name)
        setattr(obj, name, lambda *args, **kwargs: hook(original, *args, **kwargs))


class Client:
    def __init__(self):
        self.trace = []
        self.paused = True
        self.collisions = 0
        self.front_quaternion = quaternion()
        self.state = Message(position=vector(1, 2, -3), orientation=quaternion())
        self.vehicle_pose = self.state

    def simContinueForFrames(self, count):
        self.trace.append("upstream_frame")

    def simContinueForTime(self, seconds):
        self.trace.append(("timed_continuation", seconds))

    def getMultirotorState(self, vehicle_name):
        return Message(timestamp=100, kinematics_estimated=self.state)

    def simPause(self, is_paused):
        self.trace.append("pause")
        self.paused = is_paused

    def simIsPause(self):
        return self.paused

    def simSetKinematics(self, state, ignore_collision, vehicle_name):
        self.trace.append("kinematics")
        self.state = state

    def simSetVehiclePose(self, pose, ignore_collision, vehicle_name):
        self.trace.append("vehicle_pose")
        self.vehicle_pose = pose

    def simGetGroundTruthKinematics(self, vehicle_name):
        return self.state

    def simGetVehiclePose(self, vehicle_name):
        return self.vehicle_pose

    def simGetImages(self, requests):
        self.trace.append("images")
        return [Message(time_stamp=100, image_type=r.image_type, width=256, height=256,
                        camera_position=vector(1, 2, -3), camera_orientation=self.front_quaternion,
                        message="") for r in requests]


class ResetProtocolTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = Path.cwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.settings = Path("airsim_plugin/settings/30001/settings.json")
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"Vehicles": {"Drone_1": {"Cameras": {
            "FrontCamera": {"Roll": 0, "Pitch": 0, "Yaw": 0},
            "DownCamera": {"X": 0, "Y": 0, "Z": 0}}}}}))
        self.client, self.runtime = Client(), Runtime()
        reference = {"position": [1, 2, -3], "orientation": [0, 0, 0, 1]}
        def sensor_info():
            self.client.trace.append("sensor_refresh")
            self.client.collisions += 1
            return [[{"sensors": {"state": copy.deepcopy(reference), "imu": {"time_stamp": 100}}}]]
        self.env = SimpleNamespace(batch_size=1, batch=[{"trajectory": [reference]}],
            simulator_tool=SimpleNamespace(airsim_clients=[[self.client]], airsim_ports=[30001], getSensorInfo=sensor_info),
            sim_states=[SimpleNamespace(trajectory=[{"old": "cached"}])],
            update_measurements=lambda: self.client.trace.append("measurements_refreshed"))
        def original():
            for _ in range(4):
                self.client.simContinueForFrames(1)
            self.client.trace.append("original_target_spawn_and_measurements_finished")
        self.env.changeToNewTrajectorys = original
        self.api = SimpleNamespace(KinematicsState=Message, Vector3r=vector, Quaternionr=quaternion,
            Pose=lambda position_val, orientation_val: Message(position=position_val, orientation=orientation_val))
        self.requests = [Message(camera_name=camera, image_type=kind, pixels_as_float=kind == 2, compress=False)
            for camera in ("FrontCamera", "LeftCamera", "RightCamera", "RearCamera", "DownCamera") for kind in (0, 2)]

    def tearDown(self):
        os.chdir(self.previous_cwd)
        self.tmp.cleanup()

    def start(self, name=protocol.PROTOCOL):
        helper = protocol.install(self.env, self.runtime, name, self.api)
        self.env.changeToNewTrajectorys()
        return helper

    def test_candidate_applies_after_spawn_without_another_frame_and_refreshes_cache(self):
        helper = self.start()
        trace = self.client.trace
        self.assertEqual(trace.count("upstream_frame"), 4)
        self.assertLess(trace.index("original_target_spawn_and_measurements_finished"), trace.index("pause"))
        self.assertLess(trace.index("kinematics"), trace.index("vehicle_pose"))
        self.assertLess(trace.index("vehicle_pose"), trace.index("sensor_refresh"))
        self.assertEqual(self.client.collisions, 1)
        self.assertEqual(self.env.sim_states[0].trajectory[0]["sensors"]["state"]["position"], [1, 2, -3])
        self.assertEqual(set(vars(self.client.state)), {"position", "orientation", "linear_velocity", "angular_velocity", "linear_acceleration", "angular_acceleration"})
        self.client.simGetImages(requests=self.requests)
        self.assertTrue(all(helper.acceptance()["checks"].values()))
        self.assertEqual(self.client.collisions, 1)  # Acceptance adds no collision query.

    def test_upstream_selection_observes_requests_without_applying_candidate(self):
        helper = self.start("upstream")
        self.assertNotIn("kinematics", self.client.trace)
        self.assertNotIn("sensor_refresh", self.client.trace)
        self.client.simGetImages(requests=list(reversed(self.requests)))
        self.assertTrue(all(helper.acceptance()["checks"].values()))

    def test_timed_candidate_declares_one_continuation_before_sensor_refresh(self):
        helper = self.start(protocol.TIMED_PROTOCOL)
        trace = self.client.trace
        index = trace.index(("timed_continuation", 0.001))
        self.assertLess(trace.index("vehicle_pose"), index)
        self.assertLess(index, trace.index("sensor_refresh"))
        self.assertEqual(sum(isinstance(x, tuple) for x in trace), 1)
        self.assertEqual(trace.count("upstream_frame"), 4)
        self.client.simGetImages(requests=self.requests)
        self.assertTrue(all(helper.acceptance()["checks"].values()))
        event = next(v for k, v in self.runtime.rec.events if k == "reset_protocol.begin")
        self.assertTrue(event["frame_advance_added"])
        self.assertEqual(event["requested_continuation_seconds"], 0.001)

    def test_wrong_actual_camera_rotation_fails_despite_correct_cached_and_groundtruth_pose(self):
        helper = self.start()
        self.client.front_quaternion = quaternion(0, 0, math.sin(0.1), math.cos(0.1))
        self.client.simGetImages(requests=self.requests)
        result = helper.acceptance()
        self.assertTrue(result["checks"]["groundtruth_orientation_within_tolerance"])
        self.assertFalse(result["checks"]["FrontCamera_0_captured_pose_within_tolerance"])
        self.assertFalse(result["checks"]["FrontCamera_2_captured_pose_within_tolerance"])

    def test_changed_extrinsics_fail_without_assuming_transform(self):
        helper = self.start()
        settings = json.loads(self.settings.read_text())
        settings["Vehicles"]["Drone_1"]["Cameras"]["FrontCamera"]["Roll"] = 1
        self.settings.write_text(json.dumps(settings))
        self.client.simGetImages(requests=self.requests)
        result = helper.acceptance()
        self.assertFalse(result["checks"]["camera_extrinsics_verified"])
        self.assertFalse(result["checks"]["captured_camera_pose_checks_available"])

    def test_wrong_request_mapping_and_missing_capture_fail(self):
        helper = self.start()
        with self.assertRaisesRegex(ValueError, "No actual image capture"):
            helper.acceptance()
        self.requests[0].camera_name = "WrongCamera"
        self.client.simGetImages(requests=self.requests)
        self.assertFalse(helper.acceptance()["checks"]["camera_request_response_mapping_verified"])


if __name__ == "__main__":
    unittest.main()
