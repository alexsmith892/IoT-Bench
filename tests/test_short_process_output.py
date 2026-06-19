"""short_process_output must surface the actual build diagnostic.

Regression guard for a live-test finding: compiler/linker errors live at the END
of a build log (after all the "[N/M] Generating ..." progress lines), so keeping
only the head dropped the one line explaining a CF. The reason string must carry
the real error, not just cmake's progress banner.
"""

import subprocess
import unittest

from bench.runner import short_process_output


def _cp(stdout="", stderr="", returncode=1):
    return subprocess.CompletedProcess(args=["build"], returncode=returncode, stdout=stdout, stderr=stderr)


class ShortProcessOutputTests(unittest.TestCase):
    def test_short_output_returned_verbatim(self):
        self.assertEqual(short_process_output(_cp(stdout="boom")), "boom")

    def test_empty_output(self):
        self.assertEqual(short_process_output(_cp()), "no command output")

    def test_diagnostic_at_end_is_surfaced_over_progress_head(self):
        progress = "\n".join(f"[{i}/181] Generating include/generated/file_{i}.h" for i in range(1, 200))
        log = (
            progress
            + "\n[200/181] Building C object .../main.c.obj"
            + "\nC:/x/src/main.c:1:10: fatal error: zephyr.h: No such file or directory"
            + "\nninja: build stopped: subcommand failed."
        )
        out = short_process_output(_cp(stdout=log))
        self.assertIn("fatal error: zephyr.h", out)
        self.assertNotIn("Generating include/generated/file_5.h", out)

    def test_linker_error_surfaced(self):
        log = "\n".join(f"[{i}/50] cc obj{i}" for i in range(1, 80))
        log += "\n/usr/bin/ld: undefined reference to `app_main'"
        out = short_process_output(_cp(stderr=log))
        self.assertIn("undefined reference", out)

    def test_prefers_diagnostic_over_echoed_werror_command(self):
        # ninja echoes the failing gcc command (which contains -Werror=all) right
        # before the real diagnostic; the reason must surface the diagnostic, not
        # the giant compile command line.
        # Long enough (>1500 chars) to trigger diagnostic extraction, like a real
        # idf build command with hundreds of -I include paths.
        gcc_cmd = "ccache xtensa-esp32s3-elf-gcc.exe " + "-Wno-error=unused-variable " * 120 + "-o main.c.obj -c main.c"
        log = "\n".join(
            [
                "[36/1074] Building C object foo/error_capture.c.obj",
                "FAILED: esp-idf/main/CMakeFiles/__idf_main.dir/main.c.obj",
                gcc_cmd,
                "C:/app/main/main.c:9:29: error: 'LEDC_HIGH_SPEED_MODE' undeclared (first use in this function)",
                "ninja: build stopped: subcommand failed.",
            ]
        )
        out = short_process_output(_cp(stdout=log))
        self.assertIn("LEDC_HIGH_SPEED_MODE", out)
        self.assertNotIn("-Wno-error=unused-variable", out)

    def test_tail_fallback_when_no_recognizable_error(self):
        log = "x" * 5000 + "TAIL_MARKER"
        out = short_process_output(_cp(stdout=log))
        self.assertTrue(out.startswith("..."))
        self.assertIn("TAIL_MARKER", out)
        self.assertLessEqual(len(out), 1500)


if __name__ == "__main__":
    unittest.main()
