"""Cog registry: capability gating, privacy gating, and load provenance.

Everything a node runs passes through `CogRegistry.load`. Three checks, in order,
each of which produces a *reason* rather than a silent skip:

1. **Capability** — does this node's hardware actually support the cog?
2. **Resource** — does it have the RAM the cog declared?
3. **Privacy** — is the cog's privacy class at or below the node's ceiling?

A rejection is not an error. It is a recorded fact, written to the provenance
log and surfaced in the console, so an operator can always answer "why am I not
getting breathing rate on this node?" without reading source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Type

from rudestorm.cogs.base import (
    DEFAULT_PRIVACY_CEILING,
    Cog,
    CogManifest,
    NodeProfile,
    PrivacyClass,
)
from rudestorm.governance import ProvenanceLog


class CogRejected(Exception):
    """Raised by `load` when a cog cannot run here and `strict` is set."""


@dataclass(frozen=True)
class LoadResult:
    """Outcome of attempting to load one cog."""

    cog_id: str
    loaded: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {"cog_id": self.cog_id, "loaded": self.loaded, "reason": self.reason}


class CogRegistry:
    """Holds the cogs a single node is running.

    `privacy_ceiling` defaults to COARSE_PRESENCE. Raising it is an explicit,
    logged act — see `unlock_privacy_class`. This is what keeps "we do not infer
    identity or vitals" true by construction on deployments that claim it, while
    still allowing deployments that are licensed for it to turn it on.
    """

    def __init__(
        self,
        node: NodeProfile,
        log: Optional[ProvenanceLog] = None,
        privacy_ceiling: PrivacyClass = DEFAULT_PRIVACY_CEILING,
    ) -> None:
        self.node = node
        self.log = log
        self._ceiling = privacy_ceiling
        self._cogs: Dict[str, Cog] = {}
        self._results: List[LoadResult] = []

    # ---------------------------------------------------------------- privacy

    @property
    def privacy_ceiling(self) -> PrivacyClass:
        return self._ceiling

    def unlock_privacy_class(self, ceiling: PrivacyClass, authorization: str) -> None:
        """Raise the privacy ceiling. Requires a non-empty authorization string.

        The authorization (a change ticket, a signed customer consent reference,
        an ethics-board approval id) is written to the provenance chain, so the
        decision to enable biometric sensing is itself tamper-evident.
        """
        if not authorization.strip():
            raise ValueError(
                "raising the privacy ceiling requires a non-empty authorization "
                "reference; this decision must be attributable"
            )
        previous = self._ceiling
        self._ceiling = ceiling
        self._record(
            "privacy_ceiling_changed",
            {
                "from": previous.label,
                "to": ceiling.label,
                "authorization": authorization,
                "node_tier": self.node.tier,
            },
        )

    # ------------------------------------------------------------------ load

    def load(self, cog_cls: Type[Cog], source_id: str, strict: bool = False) -> LoadResult:
        """Attempt to load one cog onto this node."""
        manifest = cog_cls.manifest
        reason = self._rejection_reason(manifest)

        if reason:
            result = LoadResult(manifest.cog_id, loaded=False, reason=reason)
            self._results.append(result)
            self._record("cog_rejected", {**manifest.to_dict(), "reason": reason})
            if strict:
                raise CogRejected(f"{manifest.cog_id}: {reason}")
            return result

        cog = cog_cls(source_id)
        cog.on_load(self.node)
        self._cogs[manifest.cog_id] = cog
        result = LoadResult(manifest.cog_id, loaded=True)
        self._results.append(result)
        self._record("cog_loaded", {**manifest.to_dict(), "source_id": source_id})
        return result

    def load_all(
        self, cog_classes: Iterable[Type[Cog]], source_id: str
    ) -> List[LoadResult]:
        """Load a catalog, keeping whatever this node can run."""
        return [self.load(c, source_id) for c in cog_classes]

    def _rejection_reason(self, manifest: CogManifest) -> str:
        missing = self.node.missing(list(manifest.requires))
        if missing:
            names = ", ".join(c.value for c in missing)
            note = f" ({self.node.notes})" if self.node.notes else ""
            return (
                f"node tier '{self.node.tier}' lacks required capability: {names}{note}"
            )
        if manifest.min_ram_mb > self.node.ram_mb:
            return (
                f"needs {manifest.min_ram_mb} MB RAM, node has {self.node.ram_mb} MB"
            )
        if manifest.privacy_class > self._ceiling:
            return (
                f"privacy class '{manifest.privacy_class.label}' exceeds node "
                f"ceiling '{self._ceiling.label}'; call unlock_privacy_class() "
                "with an authorization reference to enable"
            )
        return ""

    # --------------------------------------------------------------- queries

    def get(self, cog_id: str) -> Optional[Cog]:
        return self._cogs.get(cog_id)

    @property
    def active(self) -> List[Cog]:
        return list(self._cogs.values())

    @property
    def results(self) -> List[LoadResult]:
        return list(self._results)

    def catalog(self) -> List[dict]:
        """Everything attempted on this node, loaded or not, with reasons."""
        by_id = {c.manifest.cog_id: c.manifest for c in self._cogs.values()}
        out = []
        for r in self._results:
            entry = r.to_dict()
            if r.cog_id in by_id:
                entry["manifest"] = by_id[r.cog_id].to_dict()
            out.append(entry)
        return out

    def _record(self, action: str, payload: dict) -> None:
        if self.log is not None:
            self.log.append(action, payload)
