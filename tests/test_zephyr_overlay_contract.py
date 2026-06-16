"""Offline guards for the Zephyr model-facing devicetree contract.

Two distinct drifts can silently break a *correct* model submission while the
reference solution keeps passing (the reference reaches hardware through raw
``gpio0``/``gpio1`` node labels, so it never exercises the aliases the prompt
advertises):

1. **Prompt/overlay alias drift.** A prompt tells the submission to use a
   canonical devicetree alias (e.g. ``my-led``), but ``zephyr_app_overlay`` does
   not emit that alias. ``DT_ALIAS(my_led)`` then fails to compile and the
   submission is wrongly charged a CF. ``test_prompt_aliases_are_emitted`` parses
   every prompt and asserts each advertised alias is present in the harness-owned
   overlay.

2. **Stale tracked overlay.** ``app.overlay`` is harness-owned and rewritten from
   ``zephyr_app_overlay(task)`` on every build (``ensure_zephyr_project_files``),
   so the copy tracked under ``cases/*/sketch/*/app.overlay`` is only a snapshot.
   A backend change can leave that snapshot stale and misleading.
   ``test_tracked_overlay_matches_regeneration`` byte-compares it to the
   generator, mirroring ``test_renode_regen_drift`` for ``case.repl``.

Neither guard needs Renode or west.
"""

from __future__ import annotations

import glob
import re
import unittest
from pathlib import Path

from bench.config import iter_tasks, load_task
from bench.runner import zephyr_app_overlay

PLATFORM = "zephyr_nano33ble"
REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = REPO_ROOT / "cases"
PROMPTS_GLOB = "tasks/zephyr_nano33ble/**/*.prompt.md"

# Hyphenated lowercase backtick tokens in the prompts are devicetree aliases
# today, but guard against a future prompt quoting a compatible string, header,
# or hyphenated English phrase that merely *looks* like an alias.
_NON_ALIAS_HYPHENATED = frozenset(
    {
        "gpio-leds",
        "nrf-twi",
        "nrf-twim",
        "active-high",
        "active-low",
        "non-blocking",
        "third-party",
        "real-time",
        "open-drain",
    }
)


def _renode_tasks():
    for level in ("level1", "level2", "level3"):
        yield from iter_tasks(platform=PLATFORM, level=level)


def _prompt_path(task_id: str) -> Path | None:
    matches = glob.glob(
        str(REPO_ROOT / "tasks" / PLATFORM / "**" / f"{task_id}.prompt.md"),
        recursive=True,
    )
    return Path(matches[0]) if matches else None


def _prompt_aliases(text: str) -> set[str]:
    """Devicetree aliases a prompt advertises to the model under test.

    Aliases are hyphenated (``my-led``) so a node label or raw pin reference is
    never mistaken for one. The harness emits them verbatim (hyphenated) in the
    overlay's ``aliases {}`` block; ``DT_ALIAS`` translates the hyphen to an
    underscore on the consuming side.
    """

    aliases: set[str] = set()
    for token in re.findall(r"`([^`]+)`", text):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", token):
            continue
        if "-" not in token:
            continue
        if token in _NON_ALIAS_HYPHENATED:
            continue
        aliases.add(token)
    return aliases


def _emitted_aliases(overlay: str) -> set[str]:
    return set(re.findall(r"^\s*([a-z0-9][a-z0-9-]*) = &", overlay, re.MULTILINE))


class ZephyrOverlayContractTests(unittest.TestCase):
    def test_prompt_files_present(self) -> None:
        present = list(glob.glob(str(REPO_ROOT / PROMPTS_GLOB), recursive=True))
        self.assertTrue(present, "no Zephyr prompt files found under tasks/")

    def test_prompt_aliases_are_emitted(self) -> None:
        # Runs for supported *and* unsupported tasks: a stub's prompt still
        # advertises aliases, and its overlay generator path still runs, so the
        # contract must hold before the task is ever promoted.
        checked = 0
        for task in _renode_tasks():
            prompt_path = _prompt_path(task.task_id)
            if prompt_path is None:
                continue
            advertised = _prompt_aliases(prompt_path.read_text(encoding="utf-8"))
            if not advertised:
                continue
            checked += 1
            with self.subTest(task=task.task_id):
                emitted = _emitted_aliases(zephyr_app_overlay(task))
                missing = sorted(advertised - emitted)
                self.assertFalse(
                    missing,
                    f"{task.task_id}: prompt advertises devicetree alias(es) "
                    f"{missing} that zephyr_app_overlay() does not emit. Either "
                    f"emit them in the overlay or change the prompt to give raw "
                    f"GPIO node/pin instead of an alias.",
                )
        self.assertGreater(
            checked,
            0,
            "no prompt advertised any devicetree alias - extractor likely broke",
        )

    def test_tracked_overlay_matches_regeneration(self) -> None:
        checked = 0
        for task in _renode_tasks():
            if not task.is_supported:
                continue
            sketch_overlays = glob.glob(
                str(CASES_DIR / task.case_id / "sketch" / "*" / "app.overlay")
            )
            if not sketch_overlays:
                continue
            checked += 1
            with self.subTest(task=task.task_id):
                expected = zephyr_app_overlay(task)
                actual = Path(sketch_overlays[0]).read_text(encoding="utf-8")
                self.assertEqual(
                    expected,
                    actual,
                    f"{sketch_overlays[0]} is stale; regenerate with "
                    f"`python -m bench.cli generate --task {task.task_id}`",
                )
        self.assertGreater(checked, 0, "no tracked sketch app.overlay files found")


if __name__ == "__main__":
    unittest.main()
