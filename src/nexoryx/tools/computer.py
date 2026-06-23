"""Computer-Control-Tools — Screenshot, Maus, Tastatur.

Zero-Setup-Hierarchie (automatisch, kein manuelles Aktivieren):
  1. python-xlib + XTEST  — bereits installiert (pyautogui-Abhängigkeit)
                            Keyboard/Maus direkt über X11-Protokoll injizieren
  2. pyautogui            — Fallback, ebenfalls bereits installiert
  3. xdotool/ydotool      — Subprocess-Fallback wenn installiert

Display-Erkennung (automatisch, kein DISPLAY setzen nötig):
  1. DISPLAY-Env bereits gesetzt
  2. X11-Sockets in /tmp/.X11-unix scannen
  3. /proc/<pid>/environ aller eigenen Prozesse scannen → findet Display
     auch wenn Nexoryx als systemd-Dienst ohne DISPLAY-Env läuft
  4. XAUTHORITY wird aus demselben Prozess übernommen (kein xauth-Setup)

Alle Aktionen landen im Audit-Log (tool.run via registry).
"""

from __future__ import annotations

import base64
import glob
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import Tool, ToolContext, ToolResult

# Keysym-Mapping: kurze Namen → X11-Keysym-Namen
_KEYSYM_MAP: dict[str, str] = {
    "ctrl": "Control_L", "control": "Control_L",
    "alt": "Alt_L", "option": "Alt_L",
    "shift": "Shift_L",
    "super": "Super_L", "win": "Super_L", "cmd": "Super_L",
    "meta": "Meta_L",
    "enter": "Return", "return": "Return",
    "tab": "Tab",
    "esc": "Escape", "escape": "Escape",
    "space": "space",
    "backspace": "BackSpace", "bksp": "BackSpace",
    "delete": "Delete", "del": "Delete",
    "insert": "Insert",
    "home": "Home", "end": "End",
    "pageup": "Page_Up", "pgup": "Page_Up",
    "pagedown": "Page_Down", "pgdn": "Page_Down",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "printscreen": "Print", "prtsc": "Print",
    "pause": "Pause", "capslock": "Caps_Lock",
    "numlock": "Num_Lock", "scrolllock": "Scroll_Lock",
    **{f"f{n}": f"F{n}" for n in range(1, 13)},
}


# --------------------------------------------------------------------------- #
# Display-Erkennung                                                            #
# --------------------------------------------------------------------------- #

def _find_display() -> str | None:
    """Display-String ermitteln — zero-setup, keine manuellen Schritte nötig.

    Reihenfolge:
      1. DISPLAY-Env bereits gesetzt
      2. X11-Sockets /tmp/.X11-unix/*
      3. /proc-Scan eigener Prozesse (funktioniert auch im Daemon-Betrieb)
    """
    if os.environ.get("DISPLAY"):
        return os.environ["DISPLAY"]

    # 2. X11-Sockets
    try:
        sockets = sorted(
            (p for p in os.listdir("/tmp/.X11-unix") if p.startswith("X")),
            key=lambda s: int(s[1:] or "0"),
        )
        if sockets:
            display = f":{sockets[0][1:]}"
            os.environ["DISPLAY"] = display
            _inherit_xauth_from_proc(display)
            return display
    except OSError:
        pass

    # 3. /proc-Scan: eigene Prozesse nach DISPLAY durchsuchen
    return _scan_proc_for_display()


def _scan_proc_for_display() -> str | None:
    """Laufende User-Prozesse nach DISPLAY + XAUTHORITY durchsuchen."""
    uid = os.getuid()
    for env_path in glob.glob("/proc/*/environ"):
        try:
            pid = env_path.split("/")[2]
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            data = Path(env_path).read_bytes()
            display = xauth = None
            for item in data.split(b"\x00"):
                if item.startswith(b"DISPLAY=") and len(item) > 8:
                    display = item[8:].decode(errors="replace")
                elif item.startswith(b"XAUTHORITY="):
                    xauth = item[11:].decode(errors="replace")
            if display:
                os.environ["DISPLAY"] = display
                if xauth and Path(xauth).exists():
                    os.environ["XAUTHORITY"] = xauth
                elif Path.home().joinpath(".Xauthority").exists():
                    os.environ.setdefault("XAUTHORITY",
                                         str(Path.home() / ".Xauthority"))
                return display
        except OSError:
            pass
    return None


def _inherit_xauth_from_proc(display: str) -> None:
    """XAUTHORITY aus einem Prozess holen der dasselbe Display nutzt."""
    if os.environ.get("XAUTHORITY"):
        return
    fallback = Path.home() / ".Xauthority"
    if fallback.exists():
        os.environ["XAUTHORITY"] = str(fallback)
        return
    uid = os.getuid()
    for env_path in glob.glob("/proc/*/environ"):
        try:
            pid = env_path.split("/")[2]
            if os.stat(f"/proc/{pid}").st_uid != uid:
                continue
            data = Path(env_path).read_bytes()
            d = xa = None
            for item in data.split(b"\x00"):
                if item.startswith(b"DISPLAY="):
                    d = item[8:].decode(errors="replace")
                elif item.startswith(b"XAUTHORITY="):
                    xa = item[11:].decode(errors="replace")
            if d == display and xa and Path(xa).exists():
                os.environ["XAUTHORITY"] = xa
                return
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Backend                                                                      #
# --------------------------------------------------------------------------- #

def _backend() -> str:
    """Bestes verfügbares Input-Backend — automatisch, zero-setup."""
    if _find_display():
        try:
            from Xlib import display as _xd  # noqa: F401
            from Xlib.ext import xtest as _xt  # noqa: F401
            return "xtest"
        except Exception:
            pass
        try:
            import pyautogui  # noqa: F401
            return "pyautogui"
        except Exception:
            pass
        if shutil.which("xdotool"):
            return "xdotool"
    if shutil.which("ydotool"):
        return "ydotool"
    return "none"


def _no_backend_error() -> ToolResult:
    return ToolResult(
        False, "",
        "Kein Display verfügbar. Nexoryx Computer-Control braucht eine "
        "laufende Desktop-Session (X11/XWayland). Starte Nexoryx aus einem "
        "Desktop-Terminal — dann wird der Display automatisch erkannt.",
    )


def _run_sub(args: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(args, capture_output=True, text=True, timeout=10,
                       env=os.environ.copy())
    return r.returncode, r.stdout, r.stderr


# --------------------------------------------------------------------------- #
# XTEST-Implementierungen (bereits installiert, zero-setup)                   #
# --------------------------------------------------------------------------- #

def _xtest_display():
    """Gibt (Xlib.display.Display, xtest-Modul) zurück oder (None, None)."""
    try:
        from Xlib import display as xdisp
        from Xlib.ext import xtest
        d = xdisp.Display(os.environ.get("DISPLAY"))
        if not d.has_extension("XTEST"):
            d.close()
            return None, None
        return d, xtest
    except Exception:
        return None, None


def _keysym(name: str):
    from Xlib import XK
    canonical = _KEYSYM_MAP.get(name.lower(), name)
    ks = XK.string_to_keysym(canonical)
    if ks == 0:
        ks = XK.string_to_keysym(name)
    return ks


def _xtest_key(keys: str) -> ToolResult:
    from Xlib import X
    d, xt = _xtest_display()
    if d is None:
        return ToolResult(False, "", "XTEST nicht verfügbar")
    try:
        parts = [k.strip() for k in keys.split("+")]
        keycodes = []
        for part in parts:
            ks = _keysym(part)
            kc = d.keysym_to_keycode(ks)
            if kc == 0:
                return ToolResult(False, "", f"Unbekannte Taste: {part!r}")
            keycodes.append(kc)
        for kc in keycodes:
            xt.fake_input(d, X.KeyPress, kc)
        d.sync()
        for kc in reversed(keycodes):
            xt.fake_input(d, X.KeyRelease, kc)
        d.sync()
        return ToolResult(True, f"Taste: {keys}")
    except Exception as e:
        return ToolResult(False, "", str(e))
    finally:
        d.close()


def _xtest_type(text: str, interval: float = 0.02) -> ToolResult:
    import time
    from Xlib import X
    d, xt = _xtest_display()
    if d is None:
        return ToolResult(False, "", "XTEST nicht verfügbar")
    try:
        for ch in text:
            ks = ord(ch)
            kc = d.keysym_to_keycode(ks)
            if kc == 0:
                continue
            xt.fake_input(d, X.KeyPress, kc)
            xt.fake_input(d, X.KeyRelease, kc)
            d.sync()
            if interval > 0:
                time.sleep(interval)
        return ToolResult(True, f"Eingabe: {text[:60]!r}{'…' if len(text) > 60 else ''}")
    except Exception as e:
        return ToolResult(False, "", str(e))
    finally:
        d.close()


def _xtest_click(x: int, y: int, button: str = "left", double: bool = False) -> ToolResult:
    from Xlib import X
    d, xt = _xtest_display()
    if d is None:
        return ToolResult(False, "", "XTEST nicht verfügbar")
    btn = {"left": 1, "middle": 2, "right": 3}.get(button, 1)
    try:
        xt.fake_input(d, X.MotionNotify, False, x=x, y=y)
        d.sync()
        clicks = 2 if double else 1
        for _ in range(clicks):
            xt.fake_input(d, X.ButtonPress, btn)
            xt.fake_input(d, X.ButtonRelease, btn)
        d.sync()
        return ToolResult(True, f"Klick ({button}) auf ({x}, {y})")
    except Exception as e:
        return ToolResult(False, "", str(e))
    finally:
        d.close()


def _xtest_move(x: int, y: int) -> ToolResult:
    from Xlib import X
    d, xt = _xtest_display()
    if d is None:
        return ToolResult(False, "", "XTEST nicht verfügbar")
    try:
        xt.fake_input(d, X.MotionNotify, False, x=x, y=y)
        d.sync()
        return ToolResult(True, f"Maus → ({x}, {y})")
    except Exception as e:
        return ToolResult(False, "", str(e))
    finally:
        d.close()


def _xtest_scroll(clicks: int, x: int | None = None, y: int | None = None) -> ToolResult:
    from Xlib import X
    d, xt = _xtest_display()
    if d is None:
        return ToolResult(False, "", "XTEST nicht verfügbar")
    btn = 4 if clicks > 0 else 5  # 4=hoch, 5=runter
    try:
        if x is not None and y is not None:
            xt.fake_input(d, X.MotionNotify, False, x=x, y=y)
            d.sync()
        for _ in range(abs(clicks)):
            xt.fake_input(d, X.ButtonPress, btn)
            xt.fake_input(d, X.ButtonRelease, btn)
        d.sync()
        return ToolResult(True, f"Scroll: {clicks:+d}")
    except Exception as e:
        return ToolResult(False, "", str(e))
    finally:
        d.close()


def _screenshot_xlib() -> ToolResult:
    """Screenshot direkt über X11 GetImage (zero-setup, kein scrot nötig)."""
    try:
        from Xlib import display as xdisp, X
        from PIL import Image
        d = xdisp.Display(os.environ.get("DISPLAY"))
        root = d.screen().root
        geo = root.get_geometry()
        raw = root.get_image(0, 0, geo.width, geo.height, X.ZPixmap, 0xFFFFFFFF)
        # X11 liefert BGRA; letztes Byte ignorieren → RGB
        img = Image.frombytes("RGB", (geo.width, geo.height), raw.data, "raw", "BGRX")
        d.close()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="nex_screenshot_")
        os.close(fd)
        tmp = Path(tmp_path)
        tmp.write_bytes(data)
        b64 = base64.b64encode(data).decode()
        return ToolResult(
            True,
            f"Screenshot: {tmp}  ({len(data) // 1024} KB)",
            meta={"path": str(tmp), "size_kb": len(data) // 1024, "b64_preview": b64[:200]},
        )
    except Exception as e:
        return ToolResult(False, "", f"Screenshot fehlgeschlagen: {e}")


# --------------------------------------------------------------------------- #
# Tool-Klassen                                                                 #
# --------------------------------------------------------------------------- #

class ScreenshotTool(Tool):
    name = "screenshot"
    description = "Screenshot des ganzen Bildschirms. Gibt Pfad + base64-Preview zurück."
    permission = "auto"
    schema = {}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        be = _backend()
        if be == "none":
            return _no_backend_error()
        try:
            if be in ("xtest", "pyautogui"):
                return _screenshot_xlib()
            # xdotool/ydotool: CLI-Screenshot-Tools
            fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="nex_screenshot_")
            os.close(fd)
            tmp = Path(tmp_path)
            for cmd in (
                ["scrot", str(tmp)],
                ["gnome-screenshot", "-f", str(tmp)],
                ["import", "-window", "root", str(tmp)],
            ):
                if not shutil.which(cmd[0]):
                    continue
                code, _, err = _run_sub(cmd)
                if code == 0 and tmp.exists():
                    data = tmp.read_bytes()
                    b64 = base64.b64encode(data).decode()
                    return ToolResult(
                        True,
                        f"Screenshot ({cmd[0]}): {tmp}  ({len(data) // 1024} KB)",
                        meta={"path": str(tmp), "b64_preview": b64[:200]},
                    )
            return ToolResult(False, "", "Kein Screenshot-Tool gefunden (scrot/gnome-screenshot)")
        except Exception as e:
            return ToolResult(False, "", f"Screenshot fehlgeschlagen: {e}")


class KeyPressTool(Tool):
    name = "key_press"
    description = (
        "Drückt eine Taste oder Kombination. "
        "Beispiele: 'enter', 'ctrl+c', 'alt+tab', 'ctrl+shift+t', 'super'."
    )
    permission = "computer"
    schema = {"keys": "string"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        keys = args.get("keys", "").strip()
        if not keys:
            return ToolResult(False, "", "keys fehlt")
        be = _backend()
        try:
            if be == "xtest":
                return _xtest_key(keys)
            if be == "pyautogui":
                import pyautogui
                parts = [k.strip() for k in keys.split("+")]
                pyautogui.hotkey(*parts) if len(parts) > 1 else pyautogui.press(parts[0])
                return ToolResult(True, f"Taste: {keys}")
            if be == "xdotool":
                code, _, err = _run_sub(["xdotool", "key", "--clearmodifiers", keys])
                return (ToolResult(True, f"Taste: {keys}")
                        if code == 0 else ToolResult(False, "", err.strip()))
            if be == "ydotool":
                code, _, err = _run_sub(["ydotool", "key", keys])
                return (ToolResult(True, f"Taste: {keys}")
                        if code == 0 else ToolResult(False, "", err.strip()))
            return _no_backend_error()
        except Exception as e:
            return ToolResult(False, "", f"Tastendruck fehlgeschlagen: {e}")


class TypeTextTool(Tool):
    name = "type_text"
    description = "Tippt Text an der aktuellen Cursor-Position."
    permission = "computer"
    schema = {"text": "string", "interval": "float?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        text = args.get("text", "")
        interval = float(args.get("interval", 0.02))
        be = _backend()
        try:
            if be == "xtest":
                return _xtest_type(text, interval)
            if be == "pyautogui":
                import pyautogui
                pyautogui.write(text, interval=interval)
                return ToolResult(True, f"Eingabe: {text[:60]!r}{'…' if len(text) > 60 else ''}")
            if be == "xdotool":
                code, _, err = _run_sub(
                    ["xdotool", "type", f"--delay={int(interval*1000)}", "--clearmodifiers", text])
                return (ToolResult(True, f"Eingabe: {text[:60]!r}")
                        if code == 0 else ToolResult(False, "", err.strip()))
            if be == "ydotool":
                code, _, err = _run_sub(
                    ["ydotool", "type", f"--key-delay={int(interval*1000)}", text])
                return (ToolResult(True, f"Eingabe: {text[:60]!r}")
                        if code == 0 else ToolResult(False, "", err.strip()))
            return _no_backend_error()
        except Exception as e:
            return ToolResult(False, "", f"Eingabe fehlgeschlagen: {e}")


class MouseClickTool(Tool):
    name = "mouse_click"
    description = (
        "Klickt an Position (x, y). "
        "button: left | right | middle. double: true für Doppelklick."
    )
    permission = "computer"
    schema = {"x": "int", "y": "int", "button": "string?", "double": "bool?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        x, y = int(args.get("x", 0)), int(args.get("y", 0))
        button = args.get("button", "left")
        double = bool(args.get("double", False))
        be = _backend()
        try:
            if be == "xtest":
                return _xtest_click(x, y, button, double)
            if be == "pyautogui":
                import pyautogui
                (pyautogui.doubleClick if double else pyautogui.click)(x, y, button=button)
                return ToolResult(True, f"Klick ({button}) auf ({x}, {y})")
            if be == "xdotool":
                btn = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
                _run_sub(["xdotool", "mousemove", str(x), str(y)])
                for _ in range(2 if double else 1):
                    _run_sub(["xdotool", "click", "--clearmodifiers", btn])
                return ToolResult(True, f"Klick ({button}) auf ({x}, {y})")
            if be == "ydotool":
                btn = {"left": "0x00", "right": "0x01", "middle": "0x02"}.get(button, "0x00")
                _run_sub(["ydotool", "mousemove", "-a", str(x), str(y)])
                for _ in range(2 if double else 1):
                    _run_sub(["ydotool", "click", btn])
                return ToolResult(True, f"Klick ({button}) auf ({x}, {y})")
            return _no_backend_error()
        except Exception as e:
            return ToolResult(False, "", f"Klick fehlgeschlagen: {e}")


class MouseMoveTool(Tool):
    name = "mouse_move"
    description = "Bewegt den Mauszeiger an absolute Position (x, y)."
    permission = "computer"
    schema = {"x": "int", "y": "int"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        x, y = int(args["x"]), int(args["y"])
        be = _backend()
        try:
            if be == "xtest":
                return _xtest_move(x, y)
            if be == "pyautogui":
                import pyautogui
                pyautogui.moveTo(x, y, duration=0.15)
                return ToolResult(True, f"Maus → ({x}, {y})")
            if be == "xdotool":
                code, _, err = _run_sub(["xdotool", "mousemove", str(x), str(y)])
                return (ToolResult(True, f"Maus → ({x}, {y})")
                        if code == 0 else ToolResult(False, "", err.strip()))
            if be == "ydotool":
                code, _, err = _run_sub(["ydotool", "mousemove", "-a", str(x), str(y)])
                return (ToolResult(True, f"Maus → ({x}, {y})")
                        if code == 0 else ToolResult(False, "", err.strip()))
            return _no_backend_error()
        except Exception as e:
            return ToolResult(False, "", str(e))


class ScrollTool(Tool):
    name = "scroll"
    description = "Scrollt. clicks: positiv=hoch, negativ=runter. x/y optional."
    permission = "computer"
    schema = {"clicks": "int", "x": "int?", "y": "int?"}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        clicks = int(args.get("clicks", 3))
        x = int(args["x"]) if "x" in args else None
        y = int(args["y"]) if "y" in args else None
        be = _backend()
        try:
            if be == "xtest":
                return _xtest_scroll(clicks, x, y)
            if be == "pyautogui":
                import pyautogui
                kw = {"x": x, "y": y} if x is not None and y is not None else {}
                pyautogui.scroll(clicks, **kw)
                return ToolResult(True, f"Scroll: {clicks:+d}")
            if be in ("xdotool", "ydotool"):
                btn = "4" if clicks > 0 else "5"
                extra = ["--clearmodifiers"] if be == "xdotool" else []
                for _ in range(abs(clicks)):
                    _run_sub([be, "click"] + extra + [btn])
                return ToolResult(True, f"Scroll: {clicks:+d}")
            return _no_backend_error()
        except Exception as e:
            return ToolResult(False, "", str(e))
