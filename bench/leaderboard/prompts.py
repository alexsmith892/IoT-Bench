from __future__ import annotations

from bench.config import TaskConfig

from .schemas import SkillFile


OUTPUT_FORMATS = {
    "arduino": """\
Output requirements:
- Return exactly one Arduino sketch for an Arduino Mega 2560.
- Do not include explanations, file names, or multiple files.
- The sketch must be complete and compilable as a single .ino file.
""",
    "espidf": """\
Output requirements:
- Return exactly one C source file for an ESP-IDF app.
- Do not include explanations, file names, CMake files, or multiple files.
- The source must be complete and compilable as the task's main C file.
""",
    "zephyr": """\
Output requirements:
- Return exactly one C source file for a Zephyr app.
- Do not include explanations, file names, overlays, prj.conf, or multiple files.
- The source must be complete and compilable as the task's main C file.
""",
}


def compose_prompt(task: TaskConfig, skills: tuple[SkillFile, ...]) -> tuple[str, int, int]:
    """Build the model-facing prompt without reading oracle YAML fields."""

    output_format = OUTPUT_FORMATS.get(task.board_profile.build_kind)
    if output_format is None:
        raise ValueError(f"unsupported build kind for leaderboard prompt: {task.board_profile.build_kind}")
    base = task.prompt_text.rstrip() + "\n\n" + output_format.rstrip() + "\n"
    skill_text = ""
    if skills:
        parts = ["\nSelected skills:"]
        for skill in skills:
            parts.append(f"\n--- skill: {skill.name} sha256:{skill.sha256} ---\n{skill.text.rstrip()}\n")
        skill_text = "\n".join(parts)
    return base + skill_text, len(base), len(skill_text)
