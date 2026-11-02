"""Provider registry: discovery, capability aggregation, execution routing.

One object the rest of the platform talks to. It knows which providers exist,
which are actually usable right now, and how to hand a formulation to the
right one. Nothing above this layer imports a vendor module.
"""

from __future__ import annotations

from ..models import (
    BackendCapability,
    Formulation,
    Policy,
    RawResult,
    ResourceNeed,
)
from .aws import BraketProvider
from .azure import AzureQuantumProvider
from .base import Provider, ProviderStatus, ProviderUnavailable
from .dwave import DWaveProvider
from .google import GoogleProvider
from .ibm import IBMProvider
from .local import LocalProvider


def default_providers() -> list[Provider]:
    """Every provider the platform ships with.

    Order is deliberate: local first so it is the natural tiebreak winner for
    equal scores, and so a totally offline machine still has a working path.
    """
    return [
        LocalProvider(),
        IBMProvider(),
        BraketProvider(),
        AzureQuantumProvider(),
        DWaveProvider(),
        GoogleProvider(),
    ]


class Registry:
    """Aggregates providers and routes execution to the right one."""

    def __init__(self, providers: list[Provider] | None = None) -> None:
        self.providers = providers if providers is not None else default_providers()
        self._by_vendor = {p.vendor: p for p in self.providers}
        self._cap_cache: list[BackendCapability] | None = None
        self._refreshed = False

    # -------------------------------------------------------------- status
    def statuses(self) -> list[ProviderStatus]:
        return [p.status() for p in self.providers]

    def summary(self) -> dict[str, str]:
        return {s.vendor: s.status for s in self.statuses()}

    # -------------------------------------------------------- capabilities
    def capabilities(self, *, refresh: bool = False) -> list[BackendCapability]:
        """All known backends across all providers.

        Includes backends that are not currently usable, flagged via
        ``available`` / ``credentialed``, so the broker can explain the gap
        instead of silently narrowing the user's options.
        """
        if refresh or self._cap_cache is None:
            if refresh and not self._refreshed:
                self.refresh()
            caps: list[BackendCapability] = []
            for p in self.providers:
                try:
                    caps.extend(p.capabilities())
                except Exception:
                    # A broken adapter must not take down discovery.
                    continue
            self._cap_cache = caps
        return self._cap_cache

    def refresh(self) -> None:
        """Ask every credentialed provider to update live device state."""
        for p in self.providers:
            try:
                if p.sdk_available() and p.has_credentials():
                    p.refresh()
            except Exception:
                continue
        self._refreshed = True
        self._cap_cache = None

    def usable(self, policy: Policy | None = None) -> list[BackendCapability]:
        """Backends that can actually accept a job right now."""
        pol = policy or Policy()
        out = []
        for c in self.capabilities():
            if not (c.available and c.credentialed):
                continue
            if not pol.vendor_allowed(c.vendor):
                continue
            out.append(c)
        return out

    def find(self, backend_id: str) -> BackendCapability | None:
        for c in self.capabilities():
            if c.id == backend_id:
                return c
        return None

    def provider_for(self, backend: BackendCapability) -> Provider:
        p = self._by_vendor.get(backend.vendor)
        if p is None:
            raise ProviderUnavailable(f"no provider registered for vendor {backend.vendor!r}")
        return p

    # ----------------------------------------------------------- execution
    def run(
        self,
        backend: BackendCapability,
        formulation: Formulation,
        need: ResourceNeed,
        policy: Policy,
    ) -> RawResult:
        return self.provider_for(backend).run(backend, formulation, need, policy)

    # ------------------------------------------------------------ reporting
    def report(self) -> str:
        """Human-readable inventory, for ``qos backends``."""
        lines: list[str] = []
        statuses = {s.vendor: s for s in self.statuses()}
        for p in self.providers:
            st = statuses[p.vendor]
            mark = {"ready": "+", "sdk_missing": "-", "no_credentials": "!", "error": "x"}.get(
                st.status, "?"
            )
            lines.append(f"[{mark}] {p.display_name}: {st.detail}")
            hint = st.install_hint or st.credential_hint
            if hint:
                lines.append(f"      -> {hint}")
            for c in p.capabilities():
                usable = c.available and c.credentialed
                flag = "ready" if usable else "blocked"
                if c.cost_per_shot_usd:
                    cost = f"${c.cost_per_shot_usd:.5f}/shot"
                elif c.cost_per_second_usd:
                    cost = f"${c.cost_per_second_usd:.3f}/s"
                elif "quantinuum" in c.id:
                    # Quantinuum bills in HQCs from circuit depth and shots,
                    # so a per-shot or per-second rate would misrepresent it.
                    cost = "HQC-based"
                elif "paid" in c.tags:
                    cost = "paid"
                else:
                    cost = "free"
                lines.append(
                    f"        {c.id:28s} {c.max_qubits:>7}q  {c.modality.value:16s} "
                    f"{cost:>16s}  [{flag}]"
                )
                if not usable and c.unavailable_reason:
                    lines.append(f"{'':38s}  {c.unavailable_reason}")
        return "\n".join(lines)
