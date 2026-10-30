import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))

import dw_save_editor as ed  # noqa: E402

SAMPLE = '''{
	"USER_DATA.storage" : {
		"__type" : "GCShared.DataVault.DataVault`1[[GameDefinitions.ResourceType]],Assembly-CSharp",
		"value" : {
			"values" : { "GOLD" : 100, "GEM" : 5 },
			"checksum" : 0,
			"checksumSeed" : 0,
			"isTampered" : false
		}
	},
	"USER_DATA.lastPlaySkin" : {
		"__type" : "System.Object",
		"value" : {"bst001":"None"}
	}
}'''


class TextEditingTests(unittest.TestCase):
    def test_set_token_changes_only_that_value(self):
        text = ed.set_token(SAMPLE, 'GOLD', '999')
        self.assertIn('999', text)
        self.assertIn('"GEM" : 5', text)
        data = json.loads(text)
        self.assertEqual(data['USER_DATA.storage']['value']['values']['GOLD'], 999)

    def test_insert_token_adds_member(self):
        start = SAMPLE.index('"values"')
        start = SAMPLE.index('{', start)
        end = SAMPLE.index('}', start) + 1
        text = ed.insert_token(SAMPLE, 'ZED', '7', start, end)
        data = json.loads(text)
        self.assertEqual(data['USER_DATA.storage']['value']['values']['ZED'], 7)
        self.assertEqual(data['USER_DATA.storage']['value']['values']['GOLD'], 100)

    def test_last_skin_roundtrip(self):
        text = ed.set_last_skin(SAMPLE, 'elm002', 'MOONVEIL')
        self.assertEqual(ed.get_last_skins(text)['elm002'], 'MOONVEIL')
        self.assertEqual(ed.get_last_skins(text)['bst001'], 'None')

    def test_collections_roundtrip(self):
        sample = SAMPLE.replace('"USER_DATA.storage"', '"USER_DATA.collections"')
        sample = sample.replace('"GOLD" : 100', '"COL_LIL_01" : 4')
        self.assertEqual(ed.get_collections(sample), {'COL_LIL_01': 4, 'GEM': 5})
        text = ed.set_collection(sample, 'COL_LIL_01', 9)
        self.assertEqual(ed.get_collections(text)['COL_LIL_01'], 9)

    def test_checksum_helpers(self):
        self.assertEqual(ed.to_signed32(0xFFFFFFFF), -1)
        self.assertEqual(ed.to_signed32(5), 5)


class VaultChecksumTests(unittest.TestCase):
    def test_walk_vaults_finds_vault(self):
        obj = ed.parse(SAMPLE)
        paths = [p for p, _ in ed.walk_vaults(obj)]
        self.assertTrue(any('storage' in p for p in paths))


if __name__ == '__main__':
    unittest.main()
