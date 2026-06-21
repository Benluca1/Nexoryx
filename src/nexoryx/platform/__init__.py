"""Plattform-Schicht: Hardware-Erkennung, Capability-Profil, Config.

Diese Schicht ist die zentrale Wahrheit für den Rest von Nexoryx: Der
HW-Detector erzeugt ein Profil, das jede andere Schicht liest (welche Modelle,
wie viel Parallelität, welche Tools erlaubt sind).
"""

from .detect import Hardware, detect
from .profile import Profile, choose_profile, model_gates

__all__ = ["Hardware", "detect", "Profile", "choose_profile", "model_gates"]
