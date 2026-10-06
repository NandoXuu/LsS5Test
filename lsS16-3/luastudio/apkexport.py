# -*- coding: utf-8 -*-
import os
import re
import shutil
import unicodedata
import zipfile

from . import permissions as perms
from . import project as luaproject

ORIENTATION_MAP = {"landscape": "landscape", "portrait": "portrait", "auto": "all"}

PERMISSION_KEYS = ("internet", "vibrate", "camera", "microphone", "location",
                   "storage", "notifications", "bluetooth")

FEATURE_REQUIREMENTS = {
    "numpy": ["numpy"],
    "tts": ["gtts", "requests", "urllib3", "certifi", "idna",
            "charset-normalizer", "click"],
    "pygame": ["pygame"],
}
FEATURE_KEYS = ("numpy", "tts", "pygame")

CORE_REQUIREMENTS = ["python3", "kivy", "pillow", "plyer", "pyjnius", "fonttools"]

ARCH_CHOICES = ("arm64-v8a", "armeabi-v7a", "both")

INCLUDE_EXTS = "py,png,jpg,jpeg,webp,ttf,otf,json,lsp"

GAME_FILE = "game.lsp"

REQUIREMENT_RE = re.compile(r"^[A-Za-z0-9_.\-]+(?:(?:==|>=|<=|~=|!=|<|>)[0-9A-Za-z.*]+)?$")

LAUNCHER = '''# -*- coding: utf-8 -*-
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ.setdefault("KIVY_NO_ARGS", "1")
try:
    from kivy.config import Config
    Config.set("kivy", "exit_on_escape", "0")
    Config.set("graphics", "multisamples", "0")
    if Config.has_section("input"):
        for _key, _val in list(Config.items("input")):
            if "mtdev" in _val or "hidinput" in _val:
                Config.remove_option("input", _key)
except Exception:
    pass

if __name__ == "__main__":
    from luastudio.player_app import main
    main(autoload=os.path.join(HERE, "%(game)s"))
'''


def _ascii(text):
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")


def slug(name):
    out = re.sub(r"[^a-z0-9]", "", _ascii(name).lower())
    if not out or not out[0].isalpha():
        out = "game" + out
    return out[:30]


def clean_domain(domain):
    parts = []
    for seg in str(domain or "").lower().split("."):
        seg = re.sub(r"[^a-z0-9_]", "", seg)
        if seg and seg[0].isalpha():
            parts.append(seg)
    return ".".join(parts) if len(parts) >= 2 else "org.luastudio"


def default_apk_config(name=""):
    return {
        "title": name or "LuaStudio Game",
        "package_name": slug(name),
        "package_domain": "org.luastudio",
        "version": "1.0",
        "api": 33,
        "minapi": 21,
        "ndk": "25b",
        "arch": "arm64-v8a",
        "permissions": ["internet", "vibrate"],
        "features": ["numpy", "tts"],
        "extra_requirements": "",
        "wakelock": True,
    }


def _int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def normalize_config(cfg, proj=None):
    name = proj.name if proj is not None else ""
    out = default_apk_config(name)
    if isinstance(cfg, dict):
        out.update(dict((k, v) for k, v in cfg.items() if k in out))
    title = " ".join(str(out["title"] or "").split())
    out["title"] = title or name or "LuaStudio Game"
    out["package_name"] = slug(out["package_name"] or name)
    out["package_domain"] = clean_domain(out["package_domain"])
    version = re.sub(r"[^0-9A-Za-z.\-+]", "", str(out["version"] or ""))
    out["version"] = version or "1.0"
    out["api"] = _int(out["api"], 33, 21, 40)
    out["minapi"] = _int(out["minapi"], 21, 21, out["api"])
    ndk = re.sub(r"[^0-9a-z.]", "", str(out["ndk"] or "").lower())
    out["ndk"] = ndk or "25b"
    if out["arch"] not in ARCH_CHOICES:
        out["arch"] = "arm64-v8a"
    out["permissions"] = [k for k in PERMISSION_KEYS if k in (out["permissions"] or [])]
    out["features"] = [k for k in FEATURE_KEYS if k in (out["features"] or [])]
    items = []
    for item in re.split(r"[,;\n]+", str(out["extra_requirements"] or "")):
        item = item.strip()
        if REQUIREMENT_RE.match(item) and item not in items:
            items.append(item)
    out["extra_requirements"] = ", ".join(items)
    out["wakelock"] = bool(out["wakelock"])
    return out


def requirements_list(cfg):
    reqs = list(CORE_REQUIREMENTS)
    for key in cfg["features"]:
        reqs.extend(FEATURE_REQUIREMENTS[key])
    for item in cfg["extra_requirements"].split(","):
        item = item.strip()
        if item:
            reqs.append(item)
    seen = set()
    out = []
    for r in reqs:
        base = re.split(r"[=<>!~]", r, 1)[0].lower()
        if base not in seen:
            seen.add(base)
            out.append(r)
    return out


def permission_names(cfg):
    names = []
    for key in cfg["permissions"]:
        for full in perms.PERMISSION_MAP.get(key, []):
            short = full.replace("android.permission.", "")
            if short not in names:
                names.append(short)
    return names


def build_spec(proj, cfg, has_icon=False):
    cfg = normalize_config(cfg, proj)
    screen = proj.screen or {}
    orientation = ORIENTATION_MAP.get(screen.get("orientation"), "landscape")
    fullscreen = 1 if screen.get("fullscreen", True) else 0
    archs = "arm64-v8a, armeabi-v7a" if cfg["arch"] == "both" else cfg["arch"]
    lines = [
        "[app]",
        "title = %s" % cfg["title"],
        "package.name = %s" % cfg["package_name"],
        "package.domain = %s" % cfg["package_domain"],
        "source.dir = .",
        "source.include_exts = %s" % INCLUDE_EXTS,
        "source.exclude_dirs = __pycache__,bin,.buildozer",
        "version = %s" % cfg["version"],
        "requirements = %s" % ",".join(requirements_list(cfg)),
        "orientation = %s" % orientation,
        "fullscreen = %d" % fullscreen,
    ]
    if has_icon:
        lines.append("icon.filename = %(source.dir)s/icon.png")
    perm_names = permission_names(cfg)
    if perm_names:
        lines.append("android.permissions = %s" % ",".join(perm_names))
    lines += [
        "android.api = %d" % cfg["api"],
        "android.minapi = %d" % cfg["minapi"],
        "android.ndk = %s" % cfg["ndk"],
        "android.archs = %s" % archs,
        "android.accept_sdk_license = True",
        "android.wakelock = %s" % ("True" if cfg["wakelock"] else "False"),
        "android.debug_artifact = apk",
        "android.release_artifact = apk",
        "",
        "[buildozer]",
        "log_level = 2",
        "warn_on_root = 1",
        "",
    ]
    return "\n".join(lines)


def _write_icon(proj, dest):
    image = luaproject.normalize_icon(proj.icon).get("image")
    if not image or not proj.path:
        return False
    src = os.path.join(proj.path, image)
    if not os.path.isfile(src):
        return False
    try:
        from PIL import Image
        img = Image.open(src).convert("RGBA")
        side = max(img.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - img.size[0]) // 2, (side - img.size[1]) // 2))
        canvas.resize((512, 512)).save(dest, "PNG")
        return True
    except Exception:
        if src.lower().endswith(".png"):
            shutil.copyfile(src, dest)
            return True
    return False


def export_template(proj, cfg, dest_root=None):
    cfg = normalize_config(cfg, proj)
    dest_root = dest_root or perms.storage_dir()
    base = (re.sub(r"[^A-Za-z0-9_-]+", "_", _ascii(proj.name)).strip("_") or "game") + "_buildozer"
    folder = os.path.join(dest_root, base)
    if os.path.exists(folder):
        if not os.path.isfile(os.path.join(folder, "buildozer.spec")):
            raise RuntimeError("a pasta %s ja existe e nao e um modelo Buildozer" % folder)
        shutil.rmtree(folder)
    os.makedirs(folder)

    engine_src = os.path.dirname(os.path.abspath(__file__))
    shutil.copytree(engine_src, os.path.join(folder, "luastudio"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    luaproject.export_lsp(proj, os.path.join(folder, GAME_FILE))
    has_icon = _write_icon(proj, os.path.join(folder, "icon.png"))

    with open(os.path.join(folder, "main.py"), "w", encoding="utf-8") as fh:
        fh.write(LAUNCHER % {"game": GAME_FILE})
    with open(os.path.join(folder, "buildozer.spec"), "w", encoding="utf-8") as fh:
        fh.write(build_spec(proj, cfg, has_icon))

    zip_path = folder + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(folder):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.join(base, os.path.relpath(full, folder))
                zf.write(full, rel.replace(os.sep, "/"))
    return folder, zip_path
