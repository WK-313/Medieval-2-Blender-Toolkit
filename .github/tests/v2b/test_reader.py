"""Run with python tests/v2b/test_reader.py; no Blender dependency."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

SOURCE = Path(os.environ["MED2_ADDON_SOURCE"]) if os.environ.get("MED2_ADDON_SOURCE") else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent / "Medieval-2-Toolkit-main", parent)
    if (candidate / "m2formats/cas.py").is_file())
spec = importlib.util.spec_from_file_location("strat_reader", SOURCE / "tasks/strat_reader.py")
reader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reader
spec.loader.exec_module(reader)


class ReaderTests(unittest.TestCase):
    def test_comments_case_paths_and_metadata(self):
        text = ("; preamble\nignore_registry\nTYPE Hero ; note\n"
                "skeleton strat_general\nscale 0.7\ntexture England, Models_StrAt/Hero face.TGA\n"
                "model_flexi_m Models_StrAt/Hero body.CAS, 25\n"
                "model_flexi Models_StrAt/Hero low.CAS, max\n"
                "shadow_model_flexi models_strat/shadow.CAS, max\n"
                "model_sprite 100, 1\nunknown future\n")
        doc = reader.parseStratText(text)
        entry = doc.entries[0]
        self.assertEqual(doc.diagnostics, [])
        self.assertEqual(doc.preamble + entry.raw, text)
        self.assertEqual(entry.type, "Hero")
        self.assertEqual(entry.scale, 0.7)
        self.assertEqual(entry.models[0].path, "Models_StrAt/Hero body.CAS")
        self.assertEqual(entry.models[0].distance, "25")
        self.assertEqual(len(entry.shadows), 1)
        self.assertEqual(entry.metadata["unknown"], ["future"])
        self.assertEqual(reader.selectStratTexture(entry, "england"), "Models_StrAt/Hero face.TGA")

    def test_malformed_and_duplicates(self):
        doc = reader.parseStratText("type X\nscale nan\nmodel_flexi no_distance\ntexture all, x.tga\ntexture ALL, y.tga\ntype x\nscale -1\ntype\ntexture all,z.tga\n")
        self.assertEqual(len(doc.entries), 2)
        self.assertEqual(doc.by_name()["x"], doc.entries[0])
        self.assertEqual(doc.entries[0].scale, 1)
        self.assertEqual(reader.selectStratTexture(doc.entries[0]), "x.tga")
        self.assertEqual(len(doc.diagnostics), 6)
        self.assertTrue(any("Line 2" in d for d in doc.diagnostics))
        self.assertIs(doc.by_name(), doc.by_name())

    def test_missing_lod_range_retains_model_and_source(self):
        text = "type rebel\r\nmodel_flexi models_strat/rebel.cas ; missing range\r\n"
        doc = reader.parseStratText(text)
        self.assertEqual(doc.entries[0].models[0].distance, "max")
        self.assertEqual(doc.entries[0].raw, text)
        self.assertEqual(doc.entries[0].metadata["model_flexi"], ["models_strat/rebel.cas"])
        self.assertIn("has no LOD distance; using max", doc.diagnostics[0])

    def test_texture_placeholders_and_root_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            data, vanilla = Path(temp) / "mod", Path(temp) / "vanilla"
            data.mkdir()
            vanilla.mkdir()
            (data / "face.tga").touch()
            (vanilla / "face.tga.dds").write_bytes(b"DDS ")
            self.assertEqual(reader.resolveStratPath(data, "face.tga", vanilla, texture=True), vanilla / "face.tga.dds")
            (data / "face.dds").write_bytes(b"DDS ")
            self.assertEqual(reader.resolveStratPath(data, "face.tga", vanilla, texture=True), data / "face.dds")
            (data / "face.dds").unlink()
            self.assertIsNone(reader.resolveStratPath(data, "face.tga", texture=True))

    def test_resolver_and_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "mod"
            vanilla = root / "vanilla"
            data.mkdir()
            vanilla.mkdir()
            assets = data / "Models_Strat"
            assets.mkdir()
            for name in ("Face.tga", "Face.tga.dds", "Body.CAS"):
                (assets / name).write_bytes(b"test")
            self.assertEqual(reader.resolveStratPath(data, r"data\models_strat\face.TGA", texture=True), assets / "Face.tga.dds")
            self.assertEqual(reader.resolveStratPath(data, "models_strat/body.cas"), assets / "Body.CAS")
            (vanilla / "fallback.cas").write_bytes(b"test")
            self.assertEqual(reader.resolveStratPath(data, "fallback.cas", vanilla), vanilla / "fallback.cas")
            for unsafe in ("../outside", "/absolute", "C:/outside", "models/../../outside", "//server/file"):
                self.assertIsNone(reader.resolveStratPath(data, unsafe, vanilla))
            descriptor = data / "descr_model_strat.txt"
            descriptor.write_bytes(b"type first\n")
            first = reader.loadStratModels(data)
            self.assertIs(reader.loadStratModels(data), first)
            descriptor.write_bytes(b"type second\n")
            self.assertEqual(reader.loadStratModels(data).entries[0].type, "second")
            self.assertIsNot(reader.loadStratModels(data), first)

    def test_real_mods(self):
        mods = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Medieval II Total War\mods")
        available = [mods / name / "data" for name in ("Divide_and_Conquer_EUR", "Third_Age_Reforged") if (mods / name / "data/descr_model_strat.txt").exists()]
        if not available:
            self.skipTest("Installed mod corpus unavailable")
        for data in available:
            doc = reader.loadStratModels(data)
            self.assertGreater(len(doc.entries), 100)
            self.assertEqual(doc.preamble + "".join(entry.raw for entry in doc.entries),
                             (data / "descr_model_strat.txt").read_bytes().decode("latin-1"))
            errors = [d for d in doc.diagnostics if "invalid" in d or "block skipped" in d]
            self.assertEqual(errors, [])
            for entry in doc.entries:
                self.assertTrue(entry.models, entry.type)
                self.assertTrue(entry.skeleton, entry.type)
            print(f"PASS {data.parent.name}: {len(doc.entries)} entries; {len(doc.diagnostics)} diagnostics")


if __name__ == "__main__":
    unittest.main(verbosity=2)
