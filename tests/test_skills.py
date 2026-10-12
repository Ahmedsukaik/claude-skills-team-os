"""The skills as files: format, triggering descriptions, supporting files, and how the demo loads
them. Also guards two rules of the build: plain English without em dashes, and no skill picked
in code on the live path."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import ROOT

from teamos.prompts import system_prompt
from teamos.skills import SkillError, SkillLibrary, load_skill_folder, parse_frontmatter
from teamos.tools import TOOLS, tool_definitions

SKILLS = ROOT / "skills"
NAMES = ["crm-update", "follow-up-email", "house-rules", "meeting-prep", "voice-note-debrief", "weekly-pipeline"]
LIBRARY = SkillLibrary.from_folder(SKILLS)


def test_the_six_skills_and_their_readme_are_there():
    assert sorted(LIBRARY.names()) == NAMES
    assert (SKILLS / "README.md").is_file()
    for name in NAMES:
        skill = LIBRARY.get(name)
        assert skill.files, f"{name} has supporting files"
        assert all(f.startswith(("references/", "examples/")) for f in skill.files)


@pytest.mark.parametrize("name", NAMES)
def test_descriptions_say_what_when_and_when_not(name):
    d = LIBRARY.get(name).description
    assert 200 <= len(d) <= 1024
    assert "Use when" in d or "Load it" in d, "says when to use it"
    assert "Do not" in d, "says when not to use it"
    assert ": " not in d and " #" not in d and "<" not in d  # a plain YAML value Claude's loader can read


@pytest.mark.parametrize("name", [n for n in NAMES if n != "house-rules"])
def test_every_task_skill_defers_to_house_rules_and_names_its_neighbours(name):
    skill = LIBRARY.get(name)
    assert skill.body.splitlines()[2].startswith("Before anything else, load house-rules unless it is already loaded in this chat")
    assert skill.description.endswith("Always load it together with house-rules.")
    others = [n for n in NAMES if n not in (name, "house-rules")]
    assert sum(n in skill.description for n in others) >= 2, "the description points near misses to the right skill"


def test_house_rules_says_it_applies_with_every_task_skill():
    d = LIBRARY.get("house-rules").description
    assert all(n in d for n in NAMES if n != "house-rules")
    body = LIBRARY.get("house-rules").body
    for rule in ("system of record", "Never guess", "timestamp rule", "explicit yes", "unclear", "Privacy", "Tone"):
        assert rule.lower() in body.lower(), rule


@pytest.mark.parametrize("name", NAMES)
def test_files_a_skill_points_to_exist(name):
    skill = LIBRARY.get(name)
    pointed = set(re.findall(r"`((?:references|examples)/[\w./-]+)`", skill.body))
    assert pointed and pointed <= set(skill.files), sorted(pointed - set(skill.files))


def test_the_system_prompt_lists_every_skill_from_its_files(tmp_path):
    prompt = system_prompt(LIBRARY)
    for skill in LIBRARY.skills.values():
        assert f"<name>{skill.name}</name>" in prompt and skill.description in prompt
    assert "SKILL.md" not in prompt and "## Steps" not in prompt  # only names and descriptions, not the instructions
    # A new skill folder shows up in the prompt and the tool enum with no code change.
    extra = tmp_path / "skills" / "lease-abstract"
    (extra / "references").mkdir(parents=True)
    (extra / "SKILL.md").write_text("---\nname: lease-abstract\ndescription: Summarises a lease. Use when asked. Do not "
                                    "use otherwise.\n---\n\n# Lease abstract\n", encoding="utf-8")
    (extra / "references" / "fields.md").write_text("# Fields\n", encoding="utf-8")
    library = SkillLibrary.from_folder(tmp_path / "skills")
    assert "<name>lease-abstract</name>" in system_prompt(library)
    load = next(t for t in tool_definitions(library) if t["name"] == "load_skill")
    assert load["input_schema"]["properties"]["name"]["enum"] == ["lease-abstract"]


def test_loading_returns_the_instructions_and_reading_is_limited_to_listed_files():
    assert LIBRARY.read_file("house-rules", "references/timestamp-rule.md").startswith("# The timestamp rule")
    for bad in ("../crm-update/SKILL.md", "SKILL.md", "/etc/passwd", "references/../../../README.md", ""):
        with pytest.raises(SkillError):
            LIBRARY.read_file("house-rules", bad)
    with pytest.raises(SkillError):
        LIBRARY.get("delete-everything")


@pytest.mark.parametrize("text, message", [
    ("name: x\n", "start with"),
    ("---\nname: x\n", "closing"),
    ("---\nname: x\ndescription: Does this: that\n---\n", "plain YAML"),
    ("---\nname: x\ndescription: \"quoted\"\n---\n", "plain YAML"),
    ("---\nname x\n---\n", "bad header"),
])
def test_a_bad_header_is_refused(text, message):
    with pytest.raises(SkillError, match=message):
        parse_frontmatter(text)


def test_the_folder_name_must_match(tmp_path):
    folder = tmp_path / "wrong-name"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: right-name\ndescription: x\n---\nbody\n", encoding="utf-8")
    with pytest.raises(SkillError, match="match the folder"):
        load_skill_folder(folder)


def test_the_live_path_never_picks_a_skill_in_code():
    """Only the model picks skills on the live path. The fixed rules (guided.py) may name them;
    the tool runner names house-rules only to refuse a write before the house rules are loaded."""
    live_path = ["teamos/agent.py", "teamos/models.py", "teamos/prompts.py", "teamos/session.py", "teamos/web.py",
                 "teamos/skills.py", "teamos/tools.py"]
    for path in live_path:
        source = (ROOT / path).read_text(encoding="utf-8")
        for name in NAMES:
            if name == "house-rules" and path == "teamos/tools.py":
                continue
            assert f'"{name}"' not in source and f"'{name}'" not in source, f"{path} names the skill {name}"
    assert {t["name"] for t in TOOLS} >= {"load_skill", "read_skill_file"}


TEXT_FILES = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in {".md", ".py", ".js", ".html", ".css", ".json", ".jsonl",
                                                                        ".toml", ".ini", ".txt"}
              and not any(part in {".venv", ".git", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache", "results"}
                          for part in p.relative_to(ROOT).parts)]


def test_no_em_dashes_anywhere():
    dashes = (chr(0x2014), chr(0x2013))  # em dash, en dash
    bad = [str(p.relative_to(ROOT)) for p in TEXT_FILES if any(d in p.read_text(encoding="utf-8") for d in dashes)]
    assert bad == []


def test_the_firm_is_called_fictional_wherever_it_appears_in_the_docs():
    for path in [ROOT / "README.md", ROOT / "docs" / "USER_GUIDE.md", SKILLS / "README.md", SKILLS / "house-rules" / "SKILL.md"]:
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "Marrowby" not in text or "fictional" in text, path.name


def test_only_example_emails_in_the_data_and_skills():
    for path in [ROOT / "crm" / "data.py", *SKILLS.rglob("*.md"), *Path(ROOT / "evals").glob("*.jsonl")]:
        for email in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", path.read_text(encoding="utf-8")):
            assert email.endswith("example.com"), (path.name, email)
