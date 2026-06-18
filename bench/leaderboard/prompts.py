from __future__ import annotations

from bench.config import TaskConfig

from .schemas import SkillFile


ARDUINO_OUTPUT_FORMAT = """\
Output requirements:
- Return exactly one Arduino sketch for an Arduino Mega 2560.
- Do not include explanations, file names, or multiple files.
- The sketch must be complete and compilable as a single .ino file.
"""


def compose_prompt(task: TaskConfig, skills: tuple[SkillFile, ...]) -> tuple[str, int, int]:
    """Build the model-facing prompt without reading oracle YAML fields."""

    base = task.prompt_text.rstrip() + "\n\n" + ARDUINO_OUTPUT_FORMAT.rstrip() + "\n"
    skill_text = ""
    if skills:
        parts = ["\nSelected skills:"]
        for skill in skills:
            parts.append(f"\n--- skill: {skill.name} sha256:{skill.sha256} ---\n{skill.text.rstrip()}\n")
        skill_text = "\n".join(parts)
    return base + skill_text, len(base), len(skill_text)

