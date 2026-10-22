"""Copy fonts without ligature substitutions (GSUB), for PDF typesetting.

MuPDF's HTML engine always applies a font's ligatures (e.g. Carlito's "ti", "tt")
and writes no usable ToUnicode entry for them, so text extracted from the output
PDF (copy/paste, search) becomes garbage like "enࢢre". Dropping GSUB keeps the
glyphs and kerning (GPOS) and makes every character map back to itself.

Used at image build time:  uvx --from fonttools python strip_ligatures.py <src dirs...> <out dir>
"""

import sys
from pathlib import Path

from fontTools.ttLib import TTFont

*sources, out = sys.argv[1:]
Path(out).mkdir(parents=True, exist_ok=True)
for source in sources:
    for path in Path(source).glob("*.ttf"):
        font = TTFont(path)
        if "GSUB" in font:
            del font["GSUB"]
        font.save(Path(out) / path.name)
        print(f"{path.name}: ligatures stripped")
