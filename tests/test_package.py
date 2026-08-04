from pathlib import Path
import inspect
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class PackageTest(unittest.TestCase):
    def test_manifest_declares_driver_and_scan(self) -> None:
        manifest = yaml.safe_load((ROOT / "package_manifest.yaml").read_text())
        names = [item["name"] for item in manifest["capabilities"]]
        self.assertEqual(
            names,
            ["robonix/skill/find_object/driver", "robonix/skill/find_object/scan"],
        )

    def test_pilot_image_fields_are_top_level(self) -> None:
        srv = (ROOT / "capabilities/lib/find_object/srv/ScanForObject.srv").read_text()
        response = srv.split("---", maxsplit=1)[1]
        self.assertIn("string image_base64", response)
        self.assertIn("string format", response)
        self.assertNotIn("sensor_msgs/Image image", response)

    def test_scan_handler_is_async_to_avoid_nested_event_loop(self) -> None:
        from find_object_skill.atlas_bridge import scan

        self.assertTrue(inspect.iscoroutinefunction(scan))


if __name__ == "__main__":
    unittest.main()
