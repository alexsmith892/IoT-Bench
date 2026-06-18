import unittest

from bench.config import load_task
from bench.leaderboard.manifest import resolve_plan
from bench.leaderboard.prompts import compose_prompt
from bench.leaderboard.skills import select_skills


class LeaderboardPromptBoundaryTests(unittest.TestCase):
    def test_prompt_includes_task_prompt_and_skills_but_not_oracle_yaml(self):
        plan = resolve_plan(
            "iot_skillsbench_v1",
            platform="arduino_mega",
            levels="1",
            task_ids="blink_led_1hz",
            skill_modes="human_expert",
        )
        resolved = plan.tasks[0]
        manifest = {
            "human_expert": {
                "use_skills": True,
                "skills_dir": "skillpacks/human_expert",
            }
        }
        skills = select_skills(
            plan.benchmark_root,
            skill_modes=manifest,
            skill_mode="human_expert",
            task_entry=resolved.manifest,
        )
        prompt, _, _ = compose_prompt(resolved.task, skills)

        self.assertIn(load_task("blink_led_1hz").prompt_text.strip().splitlines()[0], prompt)
        self.assertIn("Selected skills:", prompt)
        self.assertIn("arduino-framework.md", prompt)
        self.assertNotIn("waveform_frequency", prompt)
        self.assertNotIn("validator:", prompt)
        self.assertNotIn("fixture:", prompt)
        self.assertNotIn("case:", prompt)


if __name__ == "__main__":
    unittest.main()

