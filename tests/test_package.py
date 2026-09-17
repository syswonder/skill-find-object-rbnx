from pathlib import Path
import inspect
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class PackageTest(unittest.TestCase):
    def test_manifest_declares_driver_scan_and_review(self) -> None:
        manifest = yaml.safe_load((ROOT / "package_manifest.yaml").read_text())
        names = [item["name"] for item in manifest["capabilities"]]
        self.assertEqual(
            names,
            [
                "robonix/skill/find_object/driver",
                "robonix/skill/find_object/scan",
                "robonix/skill/find_object/review_last_scan",
            ],
        )

    def test_pilot_image_fields_are_top_level(self) -> None:
        srv = (ROOT / "capabilities/lib/find_object/srv/ScanForObject.srv").read_text()
        response = srv.split("---", maxsplit=1)[1]
        self.assertIn("string image_base64", response)
        self.assertIn("string format", response)
        self.assertNotIn("sensor_msgs/Image image", response)

        review_srv = (
            ROOT / "capabilities/lib/find_object/srv/ReviewLastScan.srv"
        ).read_text()
        review_response = review_srv.split("---", maxsplit=1)[1]
        self.assertIn("string image_base64", review_response)
        self.assertIn("string format", review_response)

    def test_scan_handler_is_async_to_avoid_nested_event_loop(self) -> None:
        from find_object_skill.atlas_bridge import scan

        self.assertTrue(inspect.iscoroutinefunction(scan))

    def test_config_documents_optional_image_persistence(self) -> None:
        config = yaml.safe_load((ROOT / "config.spec").read_text())["config"]
        self.assertIs(config["save_images"], False)
        self.assertEqual(
            config["image_output_dir"], "/data/robonix/find-object/scans"
        )
        self.assertEqual(config["scan_memory_ttl_s"], 900)


if __name__ == "__main__":
    unittest.main()
