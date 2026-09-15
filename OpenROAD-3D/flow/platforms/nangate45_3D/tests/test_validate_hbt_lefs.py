import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch


PLATFORM = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_hbt_lefs", PLATFORM / "validate_hbt_lefs.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class HbtGeometryTests(unittest.TestCase):
    @staticmethod
    def replace_landing(text, replacement):
        start = text.index("VIA hb_layer_0 DEFAULT")
        return text[:start] + text[start:].replace(
            "RECT -0.4 -0.4 0.4 0.4", replacement, 1)

    def validate_tech(self, replacement=None):
        read_text = Path.read_text
        tech = PLATFORM / "lef/NangateOpenCellLibrary.tech.lef"

        def contents(path, *args, **kwargs):
            text = read_text(path, *args, **kwargs)
            return replacement(text) if replacement and path == tech else text

        with patch.object(Path, "read_text", contents), contextlib.redirect_stdout(io.StringIO()):
            VALIDATOR.validate(PLATFORM)

    def test_current_platform(self):
        self.validate_tech()

    def test_reject_enlarged_landing(self):
        with self.assertRaisesRegex(ValueError, "centered 0.8 BY 0.8"):
            self.validate_tech(lambda text: self.replace_landing(
                text, "RECT -0.5 -0.5 0.5 0.5"))

    def test_reject_shifted_landing(self):
        with self.assertRaisesRegex(ValueError, "centered 0.8 BY 0.8"):
            self.validate_tech(lambda text: self.replace_landing(
                text, "RECT -0.3 -0.4 0.5 0.4"))

    def test_reject_enlarged_enclosure(self):
        with self.assertRaisesRegex(ValueError, "enclosure must be 0.15"):
            self.validate_tech(lambda text: text.replace(
                "ENCLOSURE 0.15 0.15", "ENCLOSURE 0.25 0.25", 1))

    def test_pitch_unchanged(self):
        with self.assertRaisesRegex(ValueError, "generated-via pitch"):
            self.validate_tech(lambda text: text.replace(
                "SPACING 6.4 BY 6.4", "SPACING 5.0 BY 5.0", 1))

    def test_cut_spacing_unchanged(self):
        with self.assertRaisesRegex(ValueError, "cut edge spacing"):
            self.validate_tech(lambda text: text.replace("SPACING 5.9", "SPACING 4.5", 1))


if __name__ == "__main__":
    unittest.main()
