# -*- coding: utf-8 -*-
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import permissions as perms
from . import project as luaproject

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAYER_MAIN = os.path.join(ROOT, "player_main.py")

_LINE_RE = re.compile(r"linha\s+(\d+)")


def precheck(proj):
    from .lua import parser
    from .lua.lexer import LuaSyntaxError
    for name in sorted(proj.scripts.keys()):
        try:
            parser.parse(proj.scripts[name])
        except LuaSyntaxError as ex:
            m = _LINE_RE.search(str(ex))
            return {"chunk": name, "line": int(m.group(1)) if m else None,
                    "message": str(ex)}
        except Exception:
            continue
    return None


def export_for_play(proj):
    tmpdir = tempfile.mkdtemp(prefix="luastudio_run_")
    dest = os.path.join(tmpdir, luaproject._safe_name(proj.name) + luaproject.LSP_EXT)
    luaproject.export_lsp(proj, dest)
    return tmpdir, dest


def can_spawn():
    return (not perms.ANDROID) and os.path.isfile(PLAYER_MAIN) and bool(sys.executable)


def spawn_player(lsp_path):
    if not can_spawn():
        return None
    try:
        return subprocess.Popen([sys.executable, PLAYER_MAIN, "--lsp", lsp_path],
                                cwd=ROOT)
    except Exception:
        return None


def cleanup(tmpdir):
    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)
