"""No invisible direction characters in source.

Bidi controls - isolates, embeddings, overrides, marks - are invisible in an
editor and in a review, and they can make code read differently from how it
runs ("Trojan Source", CVE-2021-42574). A page that shows Hebrew needs them at
runtime, and gets them as escapes like \\u2068 that anyone can see.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIDI = {0x2066, 0x2067, 0x2068, 0x2069, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E}
SKIP = {".venv", "node_modules", ".git", "reports", "__pycache__"}
SUFFIXES = {".py", ".js", ".html", ".css", ".md", ".yml", ".yaml", ".json", ".toml", ".ini"}


def hidden_direction_characters(root: Path) -> list[str]:
    found = []
    for path in root.rglob("*"):
        if path.suffix not in SUFFIXES or SKIP.intersection(path.parts) or not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            hidden = sorted({f"U+{ord(c):04X}" for c in line if ord(c) in BIDI})
            if hidden:
                found.append(f"{path.relative_to(root)}:{number} {' '.join(hidden)}")
    return found


def test_no_source_file_hides_a_direction_character():
    found = hidden_direction_characters(ROOT)

    assert not found, "invisible direction characters - write them as escapes:\n" + "\n".join(found)


def test_the_check_would_see_one(tmp_path):
    (tmp_path / "page.js").write_text(f"const x = `{chr(0x2068)}name{chr(0x2069)}`;\n", encoding="utf-8")

    assert hidden_direction_characters(tmp_path) == ["page.js:1 U+2068 U+2069"]
