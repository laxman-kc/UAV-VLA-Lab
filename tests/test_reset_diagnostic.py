"""Synthetic API doubles verify diagnostic behavior; no simulator claims."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import reset_diagnostic as diagnostic


class Vector:
    def __init__(self, x=0, y=0, z=0):
        self.x_val, self.y_val, self.z_val = x, y, z

    def to_msgpack(self):
        return vars(self)


class Quaternion(Vector):
    def __init__(self, x=0, y=0, z=0, w=1):
        super().__init__(x, y, z)
        self.w_val = w


class Message:
    def to_msgpack(self):
        return vars(self)


class Runtime:
    def __init__(self):
        self.events = []
        self.rec = SimpleNamespace(emit=lambda event, **values: self.events.append((event, values)))

    def patch(self, obj, name, hook):
        original = getattr(obj, name)
        setattr(obj, name, lambda *args, **kwargs: hook(original, *args, **kwargs))


class Client:
    def __init__(self):
        self.sets, self.resets, self.collisions = [], 0, 0
        self.history = []
        self.state = {"position": {"x_val": 1, "y_val": 2, "z_val": -3},
                      "orientation": {"x_val": 0, "y_val": 0, "z_val": 0, "w_val": 1}}

    def simIsPause(self):
        return True

    def simGetGroundTruthKinematics(self, **kwargs):
        return self.state

    def getMultirotorState(self, **kwargs):
        return {"kinematics_estimated": self.state, "timestamp": 123}

    def simGetVehiclePose(self, **kwargs):
        return self.state

    def getImuData(self, **kwargs):
        return {"time_stamp": 123, "orientation": self.state["orientation"]}

    def isApiControlEnabled(self, **kwargs):
        return False

    def simSetKinematics(self, **kwargs):
        self.sets.append(kwargs)
        self.history.append("set")
        return "returned"

    def simContinueForFrames(self, *args, **kwargs):
        return None

    def simPause(self, *args, **kwargs):
        return None

    def simSpawnObject(self, *args, **kwargs):
        return "fixture"

    def simGetImages(self, *args, **kwargs):
        return []

    def simGetCollisionInfo(self, **kwargs):
        self.collisions += 1
        return {"has_collided": True, "time_stamp": 1}

    def reset(self):
        self.resets += 1
        self.history.append("reset")


class ResetDiagnosticTests(unittest.TestCase):
    def fixture(self, variant):
        runtime, client = Runtime(), Client()
        api = SimpleNamespace(KinematicsState=Message, Vector3r=Vector, Quaternionr=Quaternion)
        reference = {"position": [1, 2, -3], "orientation": [0, 0, 0, 1]}
        d = diagnostic.Diagnostic(runtime, api, variant, reference)
        d.install(client)
        pose = Message()
        pose.position, pose.orientation = Vector(1, 2, -3), Quaternion()
        return d, client, pose

    def test_pose_preserves_identity_and_does_not_add_collision_query(self):
        d, c, p = self.fixture("pose")
        self.assertEqual(c.simSetKinematics(state=p, ignore_collision=True), "returned")
        self.assertIs(c.sets[0]["state"], p)
        self.assertEqual(c.collisions, 0)
        c.simGetCollisionInfo()
        self.assertEqual((c.collisions, d.collision_responses), (1, 1))
        self.assertEqual(d.snapshots[-1]["pose_comparisons"]["ground_truth"]["reset_position_error_m"], 0)
        self.assertEqual(c.resets, 0)

    def test_full_zero_is_explicit_complete_and_preserves_original(self):
        d, c, p = self.fixture("full-zero")
        c.simSetKinematics(state=p, ignore_collision=True)
        applied = c.sets[0]["state"]
        self.assertIsNot(applied, p)
        self.assertIsNot(applied.position, p.position)
        self.assertEqual(set(vars(applied)), {"position", "orientation", "linear_velocity", "angular_velocity",
                                              "linear_acceleration", "angular_acceleration"})
        for name in ("linear_velocity", "angular_velocity", "linear_acceleration", "angular_acceleration"):
            self.assertEqual(vars(getattr(applied, name)), {"x_val": 0.0, "y_val": 0.0, "z_val": 0.0})
        self.assertEqual(set(vars(p)), {"position", "orientation"})

    def test_reset_once_before_first_of_three_sets(self):
        d, c, p = self.fixture("reset-full-zero")
        for _ in range(3):
            c.simSetKinematics(state=p, ignore_collision=True)
            c.simContinueForFrames(1)
            c.simPause(True)
        self.assertEqual(c.history, ["reset", "set", "set", "set"])
        self.assertEqual((d.api_resets, d.set_calls, d.frame_calls), (1, 3, 3))
        self.assertEqual(c.collisions, 0)

    def test_read_error_is_explicit_and_original_mutator_error_propagates(self):
        d, c, p = self.fixture("pose")
        def broken(**kwargs):
            raise RuntimeError("fixture read failure")
        c.simGetGroundTruthKinematics = broken
        d.snapshot(c, "broken")
        self.assertEqual(d.read_errors[-1]["method"], "simGetGroundTruthKinematics")
        self.assertIsNone(d.snapshots[-1]["pose_comparisons"]["ground_truth"])
        with self.assertRaises(ValueError):
            c.simSetKinematics(p, True)
        with self.assertRaises(ValueError):
            c.simContinueForFrames(2)

    def test_actual_mutator_exception_is_not_converted_to_success(self):
        runtime, client = Runtime(), Client()
        def fail(**kwargs):
            raise RuntimeError("fixture RPC failure")
        client.simSetKinematics = fail
        api = SimpleNamespace(KinematicsState=Message, Vector3r=Vector, Quaternionr=Quaternion)
        d = diagnostic.Diagnostic(runtime, api, "pose", {"position": [1, 2, -3], "orientation": [0, 0, 0, 1]})
        d.install(client)
        pose = Message()
        pose.position, pose.orientation = Vector(1, 2, -3), Quaternion()
        with self.assertRaisesRegex(RuntimeError, "fixture RPC failure"):
            client.simSetKinematics(state=pose, ignore_collision=True)
        self.assertEqual(client.collisions, 0)


if __name__ == "__main__":
    unittest.main()
