import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "obd_reader"


def serial_touchers(root: Path) -> set[str]:
    """File names under root that import serial or use dynamic import tricks."""
    found = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(n == "serial" or n.startswith("serial.") for n in names):
                found.add(path.name)
            if isinstance(node, ast.Name) and node.id == "__import__":
                found.add(path.name)
            if isinstance(node, ast.Attribute) and node.attr == "import_module":
                found.add(path.name)
    return found


def test_only_transport_touches_serial():
    assert serial_touchers(SRC) == {"transport.py"}


def test_detector_flags_a_violation(tmp_path):
    (tmp_path / "ok.py").write_text("import json\n")
    (tmp_path / "bad1.py").write_text("import serial\n")
    (tmp_path / "bad2.py").write_text("from serial.tools import list_ports\n")
    (tmp_path / "bad3.py").write_text("m = __import__('serial')\n")
    (tmp_path / "bad4.py").write_text("import importlib\nimportlib.import_module('serial')\n")
    assert serial_touchers(tmp_path) == {"bad1.py", "bad2.py", "bad3.py", "bad4.py"}
