"""Discover and select instruction-only Agent Skills for this application."""
from dataclasses import dataclass
import json
from pathlib import Path
import re


BUNDLED = Path(__file__).resolve().parents[1] / "skills"
NAME = r"[a-z0-9]+(?:-[a-z0-9]+)*"
INVOCATION = re.compile(rf"^(?:use\s+)?@(?P<name>{NAME})(?:\s+(?:to\s+)?)?", re.IGNORECASE)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    source: str
    triggers: tuple

    def context(self):
        return {"name": self.name, "instructions": self.instructions}


def read_skill(folder):
    file = folder / "SKILL.md"
    with file.open(encoding="utf-8") as handle:
        raw = handle.read(32_769)
    if len(raw) > 32_768 or not raw.startswith("---\n"):
        raise ValueError("Expected a SKILL.md with frontmatter.")
    header, separator, body = raw[4:].partition("\n---\n")
    if not separator or not body.strip():
        raise ValueError("The skill needs a Markdown instruction body.")
    try:
        data = json.loads(header)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("Install PyYAML to read custom YAML frontmatter.") from exc
        try:
            # The safe loader rejects Python-specific tags. Reject aliases to bound expansion.
            if any(isinstance(token, yaml.AliasToken) for token in yaml.scan(header)):
                raise ValueError("Skill frontmatter cannot contain aliases.")
            data = yaml.safe_load(header)
        except (yaml.YAMLError, RecursionError) as exc:
            raise ValueError("Invalid YAML frontmatter.") from exc
    if not isinstance(data, dict):
        raise ValueError("Skill frontmatter must contain a name and description.")
    name, description = data.get("name"), data.get("description")
    if (not isinstance(name, str) or not re.fullmatch(NAME, name) or len(name) > 64 or name != folder.name
            or not isinstance(description, str) or not 0 < len(description.strip()) <= 1024):
        raise ValueError("Skill name must match its folder and have a description.")
    metadata = data.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    trigger_list = metadata.get("linux-assistant-triggers", "")
    triggers = tuple(phrase.strip().casefold() for phrase in trigger_list.split(",")
                     if phrase.strip()) if isinstance(trigger_list, str) else ()
    source = metadata.get("source", "")
    return Skill(name, description, body.strip(), source if isinstance(source, str) else "", triggers)


def discover(user_dir):
    skills, errors = {}, []
    for root in (BUNDLED, user_dir):
        if not root.is_dir():
            continue
        try:
            folders = sorted(root.iterdir())
        except OSError as exc:
            errors.append(f"{root.name}: {exc}")
            continue
        for folder in folders:
            if not (folder / "SKILL.md").is_file():
                continue
            try:
                skill = read_skill(folder)
                skills[skill.name] = skill
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append(f"{folder.name}: {exc}")
    return skills, errors


def match(skills, request):
    explicit = INVOCATION.match(request)
    if explicit:
        return skills.get(explicit["name"].casefold()), request[explicit.end():].strip()
    words = " ".join(re.findall(r"[a-z0-9]+", request.casefold()))
    candidates = []
    for skill in skills.values():
        name = r"[ -]".join(map(re.escape, skill.name.split("-")))
        spoken = re.match(rf"^(?:please )?use (?:the )?{name} skill\b[,: ]*(?:to\s+)?",
                          request, re.IGNORECASE)
        if spoken:
            return skill, request[spoken.end():].strip()
        for trigger in skill.triggers:
            if re.search(rf"(?<!\w){re.escape(trigger)}(?!\w)", words):
                candidates.append((len(trigger), skill))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None, request
