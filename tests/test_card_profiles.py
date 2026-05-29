import unittest

from app.card_profiles import load_profile, list_profiles


class CardProfilesTests(unittest.TestCase):
    def test_default_profile_exists_and_loads(self):
        profiles = list_profiles()
        self.assertIn("default", profiles)
        profile = load_profile("default")
        self.assertEqual(profile.language, "ru")
        self.assertGreater(profile.max_length, 0)

    def test_unknown_profile_falls_back_to_default(self):
        profile = load_profile("unknown_profile_name")
        self.assertEqual(profile.name, "default")


if __name__ == "__main__":
    unittest.main()
