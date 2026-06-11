"""Static checks must cover every source file Arduino would compile."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.static import StaticCheckError, validate_forbidden_calls, validate_required_patterns


def make_sketch(root: Path, files: dict[str, str]) -> Path:
    sketch_dir = root / "sketch"
    for relative, content in files.items():
        path = sketch_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return sketch_dir


CLEAN_INO = "void setup(){}\nvoid loop(){ tick(); }\n"


class StaticSourceScanTests(unittest.TestCase):
    def test_forbidden_call_in_header_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch = make_sketch(Path(tmp), {
                "blink.ino": CLEAN_INO,
                "helper.h": "inline void tick(){ delay(100); }\n",
            })
            with self.assertRaises(StaticCheckError):
                validate_forbidden_calls(sketch, ["delay"])

    def test_forbidden_call_in_nested_cpp_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch = make_sketch(Path(tmp), {
                "blink.ino": CLEAN_INO,
                "src/helper.cpp": "void tick(){ delay(100); }\n",
            })
            with self.assertRaises(StaticCheckError):
                validate_forbidden_calls(sketch, ["delay"])

    def test_forbidden_call_in_helper_comment_or_string_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch = make_sketch(Path(tmp), {
                "blink.ino": CLEAN_INO,
                "helper.h": '// delay(100)\nconst char *s = "delay(100)";\nvoid tick(){}\n',
            })
            validate_forbidden_calls(sketch, ["delay"])

    def test_build_output_inside_sketch_dir_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch = make_sketch(Path(tmp), {
                "blink.ino": CLEAN_INO,
                "build/arduino.avr.mega/generated.cpp": "void gen(){ delay(100); }\n",
                "artifacts/copy.cpp": "void gen(){ delay(100); }\n",
            })
            validate_forbidden_calls(sketch, ["delay"])

    def test_required_pattern_satisfied_by_helper_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch = make_sketch(Path(tmp), {
                "blink.ino": CLEAN_INO,
                "helper.h": "void tick(){ requiredToken(); }\n",
            })
            validate_required_patterns(sketch, ["requiredToken"])

    def test_missing_ino_still_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch = make_sketch(Path(tmp), {"helper.h": "void tick(){}\n"})
            with self.assertRaises(StaticCheckError):
                validate_forbidden_calls(sketch, ["delay"])

    def test_espidf_project_scans_c_sources_without_ino(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch = make_sketch(Path(tmp), {
                "CMakeLists.txt": "project(app)\n",
                "main/main.c": "void app_main(void){ esp_timer_get_time(); }\n",
            })
            validate_required_patterns(sketch, ["esp_timer_get_time"], build_kind="espidf")

    def test_espidf_project_requires_cmake(self):
        with tempfile.TemporaryDirectory() as tmp:
            sketch = make_sketch(Path(tmp), {"main/main.c": "void app_main(void){}\n"})
            with self.assertRaises(StaticCheckError):
                validate_required_patterns(sketch, ["app_main"], build_kind="espidf")


if __name__ == "__main__":
    unittest.main()
