import tempfile
import unittest
from pathlib import Path

import yaml

from app.skill_notes import create_skill_note_proposal, list_pending_skill_proposals


class SkillNotesTests(unittest.TestCase):
    def test_creates_pending_proposal_and_redacts_sensitive_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposal = create_skill_note_proposal(
                "router learned from https://example.com token=123456:ABCdefghijklmnopqrstuvwxyz",
                source="test",
                root=root,
            )
            data = yaml.safe_load(proposal.path.read_text(encoding="utf-8"))

        note = data["candidate_skills"][0]["source_context"]["conversation_notes"][0]
        self.assertEqual(data["status"], "pending")
        self.assertIn("[url-redacted]", note)
        self.assertIn("token=[redacted]", note)
        self.assertNotIn("https://example.com", note)

    def test_lists_pending_proposals_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = create_skill_note_proposal("first lesson", root=root)
            second = create_skill_note_proposal("second lesson", root=root)

            paths = list_pending_skill_proposals(root=root, limit=2)

        self.assertEqual(paths[0].name, second.path.name)
        self.assertEqual(paths[1].name, first.path.name)


if __name__ == "__main__":
    unittest.main()
