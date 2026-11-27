"""Payload owners on the History tab: GCAT's codes split and named (gcat.owner_codes, gcat.owner_names,
catalog._owner_labels)."""
import unittest

from launch import catalog, gcat

ORGS = gcat.orgs_table([
    {"Code": "ESA", "Name": "European Space Agency", "EName": "-", "ShortEName": "-"},
    {"Code": "ZXW", "Name": "Zhongguo Weixing", "EName": "China Satellite Network Group", "ShortEName": "China SatNet"},
    {"Code": "AAA", "Name": "Acme", "EName": "-", "ShortEName": "-"},
    {"Code": "BBB", "Name": "Acme", "EName": "-", "ShortEName": "-"},
])


class OwnerTest(unittest.TestCase):
    def test_joint_and_doubted_owners_split_into_codes(self):
        self.assertEqual(gcat.owner_codes("ESA/ZXW?"), ["ESA", "ZXW"])
        self.assertEqual((gcat.owner_codes("-"), gcat.owner_codes(None)), ([], []))

    def test_english_name_first_and_unlisted_codes_left_out(self):
        self.assertEqual(gcat.owner_names(ORGS, ["ESA/ZXW", "NOPE"]),
                         {"ESA": "European Space Agency", "ZXW": "China Satellite Network Group"})

    def test_labels_cover_the_records_owners_and_tell_shared_names_apart(self):
        names = gcat.owner_names(ORGS, ["ESA", "AAA", "BBB", "ZXW"])
        recs = [{"payloads": {"owners": ["AAA/ESA", "BBB"]}}, {"payloads": None}, {}]
        self.assertEqual(catalog._owner_labels(names, recs),
                         {"AAA": "Acme (AAA)", "BBB": "Acme (BBB)", "ESA": "European Space Agency"})


if __name__ == "__main__":
    unittest.main()
