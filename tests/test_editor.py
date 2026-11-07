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

SAMPLE_UNITS = '''{
	"USER_DATA.m_Units" : {
		"__type" : "System.Object",
		"value" : [
			{
				"__type" : "UserGameDataPack.MemoryUnitData,Assembly-CSharp",
				"id" : 1,
				"unitIdx" : "UDD901",
				"parts" : [
					{ "id" : 0, "key" : "UDD901_M1" },
					{ "id" : 1, "key" : "UDD901_S1" },
					{ "id" : 2, "key" : "UDD902_S2" }
				],
				"vault" : { "values" : { "RankUp" : 7, "TRANSCEND" : 1 } }
			}
		]
	}
}'''

SAMPLE_INGAME = '''{
	"INGAME_DATA.units" : {
		"__type" : "System.Object",
		"value" : [
			{
				"__type" : "IngameDataMgr.PlayerUnitData,Assembly-CSharp",
				"unitIndex" : "UDD901",
				"status" : "",
				"parts" : [
					{ "memoryID" : -1, "key" : "UDD901_I1",
					  "vault" : { "values" : {}, "checksum" : 0, "checksumSeed" : 0, "isTampered" : false } },
					{ "memoryID" : 0, "key" : "UDD901_M1",
					  "vault" : { "values" : {}, "checksum" : 0, "checksumSeed" : 0, "isTampered" : false } },
					{ "memoryID" : 1, "key" : "ELM102_S1",
					  "vault" : { "values" : { "Ethereal" : 1 }, "checksum" : 0, "checksumSeed" : 0,
					              "isTampered" : false } }
				]
			}
		]
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


class EtherealSlotTests(unittest.TestCase):
    def test_reads_slot_map(self):
        slots = ed.unit_part_slots(SAMPLE_UNITS, 0)
        self.assertEqual(slots, {0: 'UDD901_M1', 1: 'UDD901_S1', 2: 'UDD902_S2'})

    def test_add_ethereal_slots(self):
        text = ed.set_unit_part_slot(SAMPLE_UNITS, 0, ed.ETHEREAL_MAIN_SLOT, 'EVT009_M1')
        text = ed.set_unit_part_slot(text, 0, ed.ETHEREAL_SUB_SLOT, 'EVT009_S1')
        slots = ed.unit_part_slots(text, 0)
        self.assertEqual(slots[ed.ETHEREAL_MAIN_SLOT], 'EVT009_M1')
        self.assertEqual(slots[ed.ETHEREAL_SUB_SLOT], 'EVT009_S1')
        self.assertEqual(slots[0], 'UDD901_M1')

    def test_update_existing_slot(self):
        text = ed.set_unit_part_slot(SAMPLE_UNITS, 0, ed.ETHEREAL_MAIN_SLOT, 'EVT009_M1')
        text = ed.set_unit_part_slot(text, 0, ed.ETHEREAL_MAIN_SLOT, 'EVT001_S1')
        slots = ed.unit_part_slots(text, 0)
        self.assertEqual(slots[ed.ETHEREAL_MAIN_SLOT], 'EVT001_S1')
        self.assertEqual(len(slots), 4)

    def test_clear_slot(self):
        text = ed.set_unit_part_slot(SAMPLE_UNITS, 0, ed.ETHEREAL_MAIN_SLOT, 'EVT009_M1')
        text = ed.set_unit_part_slot(text, 0, ed.ETHEREAL_MAIN_SLOT, '')
        self.assertNotIn(ed.ETHEREAL_MAIN_SLOT, ed.unit_part_slots(text, 0))

    def test_slots_sorted_by_id(self):
        text = ed.set_unit_part_slot(SAMPLE_UNITS, 0, ed.ETHEREAL_SUB_SLOT, 'EVT009_S1')
        text = ed.set_unit_part_slot(text, 0, ed.ETHEREAL_MAIN_SLOT, 'EVT009_M1')
        parts = ed.unit_parts(text, 0)
        self.assertEqual([p['id'] for p in parts], [0, 1, 2, ed.ETHEREAL_MAIN_SLOT, ed.ETHEREAL_SUB_SLOT])


class RunUnitEtherealTests(unittest.TestCase):
    def test_reads_run_units(self):
        units = ed.ingame_units(SAMPLE_INGAME)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['unitIndex'], 'UDD901')
        self.assertEqual([p['key'] for p in units[0]['parts']], ['UDD901_I1', 'UDD901_M1', 'ELM102_S1'])
        self.assertFalse(units[0]['parts'][1]['ethereal'])
        self.assertTrue(units[0]['parts'][2]['ethereal'])

    def test_toggle_ethereal(self):
        text = ed.set_ingame_part_ethereal(SAMPLE_INGAME, 0, 1, True)
        self.assertTrue(ed.ingame_parts(text, 0)[1]['ethereal'])
        text = ed.set_ingame_part_ethereal(text, 0, 2, False)
        self.assertFalse(ed.ingame_parts(text, 0)[2]['ethereal'])

    def test_add_part(self):
        text = ed.add_ingame_part(SAMPLE_INGAME, 0, 'ELM901_M1', ethereal=True)
        parts = ed.ingame_parts(text, 0)
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[-1]['key'], 'ELM901_M1')
        self.assertTrue(parts[-1]['ethereal'])

    def test_set_key(self):
        text = ed.set_ingame_part_key(SAMPLE_INGAME, 0, 1, 'BST801_M1')
        self.assertEqual(ed.ingame_parts(text, 0)[1]['key'], 'BST801_M1')

    def test_remove_part(self):
        text = ed.remove_ingame_part(SAMPLE_INGAME, 0, 1)
        keys = [p['key'] for p in ed.ingame_parts(text, 0)]
        self.assertEqual(keys, ['UDD901_I1', 'ELM102_S1'])
        data = json.loads(text)
        self.assertEqual(len(data['INGAME_DATA.units']['value'][0]['parts']), 2)


if __name__ == '__main__':
    unittest.main()


SAMPLE_MW = """{
	"USER_DATA.mwExp" : {
		"__type" : "System.Object",
		"value" : [
			{
				"__type" : "GameDefinitions.OutExp+MWData,Assembly-CSharp",
				"UpgAspe" : { "values" : {"Basic":1}, "checksum" : 0, "checksumSeed" : 0, "isTampered" : false },
				"lcUpg" : { "values" : {"LC_BST001_B01":1,"LC_BST001_S01":2,"LC_UDD001_B01":0},
					"checksum" : 0, "checksumSeed" : 0, "isTampered" : false },
				"storage" : { "values" : {"LEVEL":1,"UNLOCKED":0,"TOKEN":0},
					"checksum" : 0, "checksumSeed" : 0, "isTampered" : false },
				"key" : "BST001",
				"level" : 1,
				"clearStage" : [1,2,3]
			},
			{
				"__type" : "GameDefinitions.OutExp+MWData,Assembly-CSharp",
				"UpgAspe" : { "values" : {"Basic":2}, "checksum" : 0, "checksumSeed" : 0, "isTampered" : false },
				"lcUpg" : { "values" : {"LC_UDD001_B01":2}, "checksum" : 0, "checksumSeed" : 0, "isTampered" : false },
				"storage" : { "values" : {"LEVEL":2,"UNLOCKED":0,"TOKEN":0},
					"checksum" : 0, "checksumSeed" : 0, "isTampered" : false },
				"key" : "UDD001",
				"level" : 2,
				"clearStage" : [1]
			}
		]
	}
}"""

SAMPLE_MAWANG = """{
	"INGAME_DATA.playerMawang" : {
		"__type" : "IngameDataMgr.PlayerMawangData,Assembly-CSharp",
		"unitIndex" : "BST001",
		"baseEft" : {"MaxHP":0.5,"Strength":0.25,"Dexterity":0.1,"Constitution":0.2,"INT":0.3,"WIS":0.4,"CHA":0.6},
		"growEft" : {"MaxHP":0.1,"Strength":0.2},
		"awakeEft" : { "values" : {"STR":1,"DEX":0,"CON":0,"INT":0,"WIS":0,"CHA":0,"HP":0,"MainStat":0},
			"checksum" : 0, "checksumSeed" : 0, "isTampered" : false },
		"parts" : [ { "key" : "BST001_B01" } ]
	}
}"""


def _bad_checksums(text):
    bad = 0
    for _, vault in ed.walk_vaults(ed.parse(text)):
        vals = vault.get('values') or {}
        if any(not isinstance(v, int) for v in vals.values()):
            continue
        x = 0
        for v in vals.values():
            x ^= int(v) & 0xFFFFFFFF
        want = ed.to_signed32((vault.get('checksumSeed', 0) ^ x) & 0xFFFFFFFF)
        if vault.get('checksum') != want:
            bad += 1
    return bad


class DarkLordStatTests(unittest.TestCase):
    def test_reads_level(self):
        self.assertEqual(ed.get_mw_level(SAMPLE_MW, 0), 1)
        self.assertEqual(ed.get_mw_level(SAMPLE_MW, 1), 2)

    def test_set_level(self):
        text = ed.set_mw_level(SAMPLE_MW, 0, 5)
        self.assertEqual(ed.get_mw_level(text, 0), 5)
        self.assertEqual(_bad_checksums(text), 0)

    def test_max_form_scales_only_its_stages(self):
        text = ed.max_mw_form(SAMPLE_MW, 0, 3)
        self.assertEqual(ed.get_mw_level(text, 0), 3)
        self.assertEqual(ed.get_mw_vault(text, 0, 'UpgAspe')['Basic'], 3)
        lc = ed.get_mw_vault(text, 0, 'lcUpg')
        self.assertEqual(lc['LC_BST001_B01'], 3)
        self.assertEqual(lc['LC_BST001_S01'], 3)
        self.assertEqual(lc['LC_UDD001_B01'], 0)
        self.assertEqual(ed.get_mw_level(text, 1), 2)
        self.assertEqual(_bad_checksums(text), 0)

    def test_max_all_forms(self):
        text = ed.max_all_mw_forms(SAMPLE_MW, 4)
        self.assertEqual(ed.get_mw_level(text, 0), 4)
        self.assertEqual(ed.get_mw_level(text, 1), 4)
        self.assertEqual(ed.get_mw_vault(text, 1, 'lcUpg')['LC_UDD001_B01'], 4)
        self.assertEqual(_bad_checksums(text), 0)

    def test_run_mawang_stats_roundtrip(self):
        st = ed.ingame_mawang_stats(SAMPLE_MAWANG)
        self.assertAlmostEqual(st['baseEft']['Strength'], 0.25)
        self.assertEqual(st['awakeEft']['STR'], 1)
        text = ed.set_ingame_mawang_stat(SAMPLE_MAWANG, 'baseEft', 'Strength', 9.5)
        st = ed.ingame_mawang_stats(text)
        self.assertAlmostEqual(st['baseEft']['Strength'], 9.5)
        text = ed.set_ingame_mawang_stat(text, 'awakeEft', 'STR', 7)
        self.assertEqual(ed.ingame_mawang_stats(text)['awakeEft']['STR'], 7)
        self.assertEqual(_bad_checksums(text), 0)

    def test_run_mawang_missing(self):
        self.assertEqual(ed.ingame_mawang_stats(SAMPLE), {})
        with self.assertRaises(KeyError):
            ed.set_ingame_mawang_stat(SAMPLE, 'baseEft', 'STR', 1)

import base64 as _b64
import hashlib as _hashlib

import dw_es3 as _es3

_ORACLE_B64 = (
    'RVMzRegybNs1mATb5fAjLBRFcvg7o5RKL2iXe43an4EiE6LM1FKhjqhhjMI542s7197kH2o5TNW520Sw20bNT+nQosfodSw/'
    'foKru24UPHzax4pdzxZpLkldZkB1UA0wr6bUGQIMDsl6BFiwWW0Yx6992ErWR/JLKAgYMABDYQM0f5F4G03ikWV4XuIGDtUTcvV5'
    'r0Zl2c/AxjEgZiBwe9gYb7E=')


class Es3ContainerTests(unittest.TestCase):
    def test_roundtrip(self):
        self.assertEqual(_es3.decrypt(_es3.encrypt(b'{"a":1}')), b'{"a":1}')

    def test_decrypts_game_container(self):
        plain = _es3.decrypt(_b64.b64decode(_ORACLE_B64))
        self.assertEqual(len(plain), 194371)
        self.assertEqual(_hashlib.sha256(plain).hexdigest(),
                         'a62103a4d71ccbd91259ac6ae73b6fbd478913484b7dcc7fb2279e82694b2ce0')

    def test_rejects_tampered_container(self):
        data = bytearray(_b64.b64decode(_ORACLE_B64))
        data[-1] ^= 1
        with self.assertRaises(_es3.ContainerError):
            _es3.decrypt(bytes(data))