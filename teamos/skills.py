"""Loads the skills in skills/ the way Claude loads them.

Claude first sees only each skill's name and description (the system prompt lists them). When a
request fits one, it calls `load_skill` and gets the SKILL.md instructions; when the
instructions point to a supporting file, it calls `read_skill_file`. Nothing here decides which
skill fits a request: that is the model's job, from the descriptions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SUFFIXES = (".md", ".txt", ".json")
MAX_DESCRIPTION = 1024


class SkillError(Exception):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str                 # SKILL.md without its YAML header
    files: tuple[str, ...]    # supporting files, as paths relative to the skill folder
    folder: Path


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """The YAML header of a SKILL.md: one `key: value` per line between two `---` lines. Values
    are plain YAML scalars, so `: ` and ` #` inside a value are refused (YAML would misread them)."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md must start with a --- line")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as e:
        raise SkillError("SKILL.md header has no closing --- line") from e
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(": ")
        if not sep or not re.fullmatch(r"[a-z_-]+", key):
            raise SkillError(f"bad header line: {line[:60]!r}")
        value = value.strip()
        if ": " in value or " #" in value or value[:1] in "\"'[{>|&*!%@`":
            raise SkillError(f"{key} is not a plain YAML value (no ': ', ' #' or leading quote)")
        meta[key] = value
    return meta, "\n".join(lines[end + 1:]).strip() + "\n"


def load_skill_folder(folder: Path) -> Skill:
    meta, body = parse_frontmatter((folder / "SKILL.md").read_text(encoding="utf-8"))
    name, description = meta.get("name", ""), meta.get("description", "")
    if name != folder.name or not NAME.match(name) or len(name) > 64:
        raise SkillError(f"{folder.name}: name must match the folder, lowercase words joined by hyphens")
    if not description or len(description) > MAX_DESCRIPTION or "<" in description or ">" in description:
        raise SkillError(f"{name}: description must be 1 to {MAX_DESCRIPTION} characters, without < or >")
    files = tuple(sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                         if p.is_file() and p.name != "SKILL.md" and p.suffix in SUFFIXES))
    return Skill(name, description, body, files, folder)


class SkillLibrary:
    def __init__(self, skills: list[Skill]):
        self.skills = {s.name: s for s in skills}

    @classmethod
    def from_folder(cls, root: Path = SKILLS_DIR) -> SkillLibrary:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
        return cls([load_skill_folder(p) for p in folders])

    def names(self) -> list[str]:
        return list(self.skills)

    def listing(self) -> str:
        """What the system prompt shows: every skill's name and description, nothing more."""
        items = "\n".join(f"<skill>\n<name>{escape(s.name)}</name>\n<description>{escape(s.description)}</description>\n</skill>"
                          for s in self.skills.values())
        return f"<available_skills>\n{items}\n</available_skills>"

    def get(self, name: str) -> Skill:
        skill = self.skills.get(name) if isinstance(name, str) else None
        if skill is None:
            raise SkillError(f"There is no skill named {name!r}. Skills: {', '.join(self.skills)}.")
        return skill

    def read_file(self, name: str, path: str) -> str:
        """A supporting file of a skill. Only files the skill lists can be read: no paths outside it."""
        skill = self.get(name)
        if not isinstance(path, str) or path not in skill.files:
            listed = ", ".join(skill.files) or "none"
            raise SkillError(f"{name} has no file {path!r}. Its files: {listed}.")
        return (skill.folder / path).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def default_library() -> SkillLibrary:
    return SkillLibrary.from_folder()
