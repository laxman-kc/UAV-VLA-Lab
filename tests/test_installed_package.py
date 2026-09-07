"""Build a real wheel, install it offline, and exercise it outside the checkout.

Run with the dev extra installed; only the isolated build needs setuptools.
The test environment receives the wheel alone, with no project/GPU dependency.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class InstalledPackageTests(unittest.TestCase):
    def test_wheel_cpu_workflow_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheels = root / "wheels"
            wheels.mkdir()
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)
            env["PYTHONNOUSERSITE"] = "1"

            def run(argv, *, success=True):
                result = subprocess.run([str(value) for value in argv], cwd=root, env=env,
                                        text=True, capture_output=True, timeout=120)
                if success:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            # Default build creates an sdist then builds its wheel in a fresh tree.
            # Direct --wheel can retain removed modules in a stale build/lib.
            run([sys.executable, "-m", "build", "--no-isolation", "--outdir", wheels, ROOT])
            wheel, = wheels.glob("*.whl")
            with zipfile.ZipFile(wheel) as archive:
                actual_sources = {name for name in archive.namelist() if name.startswith("uav_vla_lab/") and name.endswith(".py")}
                expected_sources = {path.relative_to(ROOT / "src").as_posix() for path in (ROOT / "src/uav_vla_lab").rglob("*.py")}
                self.assertEqual(actual_sources, expected_sources, "Wheel includes stale/missing Python source")
                self.assertFalse(any(name.startswith("uav_vla_lab/integrations/aerovla/legacy/") and name.endswith(".sh")
                                     for name in archive.namelist()), "Obsolete host-specific shell resources leaked into wheel")
            run([sys.executable, "-m", "venv", root / "environment"])
            bindir = root / "environment" / ("Scripts" if os.name == "nt" else "bin")
            python = bindir / ("python.exe" if os.name == "nt" else "python")
            cli = bindir / ("uav-vla.exe" if os.name == "nt" else "uav-vla")
            run([python, "-m", "pip", "install", "--no-index", "--no-deps", wheel])
            doctor = json.loads(run([cli, "doctor", "--json"]).stdout)
            self.assertEqual(doctor["status"], "ready")
            self.assertFalse(any(doctor["optional_module_presence"].values()))
            self.assertIsNotNone(doctor["core"]["installed_distribution_version"])
            historical = json.loads(run([cli, "legacy", "list"]).stdout)
            self.assertIn("scripts/build_release.py", historical["scripts"])
            run([cli, "report", "build", "--help"])
            run([cli, "evaluate", "summarize", "--help"])
            run([cli, "train", "--help"])
            bad_workflow = run([cli, "runtime", "not-a-workflow"], success=False)
            self.assertEqual(bad_workflow.returncode, 2)
            self.assertNotIn("Traceback", bad_workflow.stderr)
            first = root / "first-attempt"
            receipt = json.loads(run([cli, "demo", "--output", first]).stdout)
            self.assertEqual(receipt["metrics"]["action_count"], 4)
            self.assertIsNone(receipt["metrics"]["navigation_success"])
            verified = json.loads(run([python, "-m", "uav_vla_lab", "verify", first]).stdout)
            self.assertEqual(verified, receipt)
            second = root / "second-attempt"
            run([cli, "replay", first / "input.json", "--output", second])
            self.assertEqual((first / "metrics.json").read_bytes(), (second / "metrics.json").read_bytes())
            collision = run([cli, "demo", "--output", first], success=False)
            self.assertEqual(collision.returncode, 2)
            (first / "metrics.json").write_text("{}")
            tampered = run([cli, "verify", first], success=False)
            self.assertEqual(tampered.returncode, 2)
            self.assertNotIn("Traceback", tampered.stderr)


if __name__ == "__main__":
    unittest.main()
