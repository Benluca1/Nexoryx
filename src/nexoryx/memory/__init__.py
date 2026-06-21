"""Memory-Schicht: Multi-Layer-Speicher (Plan §5).

Short-Term (Session, in-process) + Long-Term/Project/Preference (SQLite).
Semantischer Recall ist hier keyword+recency-basiert (zero-dependency); ein
echter Vektor-Store (sqlite-vec) kann hinter `recall()` ergänzt werden.
"""

from .store import MemoryStore, Memory

__all__ = ["MemoryStore", "Memory"]
