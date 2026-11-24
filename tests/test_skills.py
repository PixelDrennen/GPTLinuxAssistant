from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from assistant_app import skills


class SkillsTests(unittest.TestCase):
    def test_bundled_skills_select_the_relevant_workflow(self):
        with TemporaryDirectory() as root:
            installed, errors = skills.discover(Path(root))
        self.assertEqual([], errors)
        self.assertEqual("desktop-navigation", skills.match(installed, "Go ahead and hit play")[0].name)
        skill, request = skills.match(installed, "Use the screenshot skill to take a screenshot")
        self.assertEqual(("screenshot", "take a screenshot"), (skill.name, request))
        self.assertEqual("look at this window", skills.match(installed, "@screenshot look at this window")[1])

    def test_custom_instruction_is_loaded_only_for_matching_requests(self):
        with TemporaryDirectory() as root:
            folder = Path(root) / "read-ledger"
            folder.mkdir()
            folder.joinpath("SKILL.md").write_text(
                '---\n{"name":"read-ledger","description":"Review a ledger",'
                '"metadata":{"linux-assistant-triggers":"TSM ledger"}}\n---\nRead the selected date range.'
            )
            installed, errors = skills.discover(Path(root))
        self.assertEqual([], errors)
        self.assertIsNone(skills.match(installed, "What time is it?")[0])
        selected = skills.match(installed, "Read my TSM ledger")[0]
        self.assertEqual({"name": "read-ledger", "instructions": "Read the selected date range."}, selected.context())
