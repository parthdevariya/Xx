"""Provider interface -- the contract every quantum platform adapter implements.

Design intent: the broker and runtime must never import a vendor SDK or know
a vendor's vocabulary. They speak only ``BackendCapability``, ``Formulation``
and ``RawResult``. Everything vendor-specific lives behind this interface, so
adding a platform means writing one adapter and nothing else changes.

Adapters must be importable with no SDK installed and no credentials present.
A missing SDK is reported as ``status="sdk_missing"`` and missing credentials
as ``status="no_credentials"``; in both cases the adapter still advertises its
devices with ``credentialed=False``. That is deliberate -- it lets the
platform tell a user "IBM Heron (133 qubits) would fit this problem, but you
have no IBM credentials configured" instead of silently pretending the option
does not exist.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..models import (
    BackendCapability,
    Formulation,
    Policy,
    RawResult,
    ResourceNeed,
)


@dataclass
class ProviderStatus:
    vendor: str
    status: str                 # ready | sdk_missing | no_credentials | error
    detail: str = ""
    install_hint: str = ""
    credential_hint: str = ""
    device_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.status == "ready"


class Provider(ABC):
    """Base class for a quantum platform adapter."""

    vendor: str = "unknown"
    display_name: str = "Unknown"
    # Python modules that must import for this provider to be usable.
    sdk_modules: tuple[str, ...] = ()
    # Environment variables that carry credentials; any one present is enough
    # unless the adapter overrides ``has_credentials``.
    credential_env: tuple[str, ...] = ()
    install_extra: str = ""

    # ------------------------------------------------------------ probing
    def sdk_available(self) -> bool:
        import importlib.util

        for mod in self.sdk_modules:
            try:
                if importlib.util.find_spec(mod) is None:
                    return False
            except (ImportError, ModuleNotFoundError, ValueError):
                # A dotted module ("azure.quantum") raises rather than
                # returning None when its parent package is absent.
                return False
        return bool(self.sdk_modules)

    def has_credentials(self) -> bool:
        return any(os.environ.get(k) for k in self.credential_env)

    def status(self) -> ProviderStatus:
        devices = self.capabilities()
        if self.sdk_modules and not self.sdk_available():
            return ProviderStatus(
                self.vendor, "sdk_missing",
                detail=f"{self.display_name} SDK not installed",
                install_hint=f"pip install 'quantum-os[{self.install_extra}]'"
                if self.install_extra else "",
                device_count=len(devices),
            )
        if self.credential_env and not self.has_credentials():
            return ProviderStatus(
                self.vendor, "no_credentials",
                detail=f"{self.display_name} SDK present but no credentials found",
                credential_hint="set " + " or ".join(self.credential_env),
                device_count=len(devices),
            )
        return ProviderStatus(
            self.vendor, "ready",
            detail=f"{self.display_name} ready",
            device_count=len(devices),
        )

    # -------------------------------------------------------- capabilities
    @abstractmethod
    def capabilities(self) -> list[BackendCapability]:
        """Devices this provider exposes.

        Should return the catalog even when unusable, with ``credentialed``
        reflecting reality, so the broker can explain what the user is missing.
        """

    def refresh(self) -> None:
        """Optionally update dynamic fields (queue depth, availability).

        Called by the registry before planning when credentials exist. Default
        is a no-op so adapters only implement it if the vendor exposes it.
        """

    # ------------------------------------------------------------ execution
    @abstractmethod
    def run(
        self,
        backend: BackendCapability,
        formulation: Formulation,
        need: ResourceNeed,
        policy: Policy,
    ) -> RawResult:
        """Execute the formulation and return a raw result.

        Must raise ``ProviderUnavailable`` rather than a vendor exception when
        the failure is environmental (no SDK, no credentials, device offline),
        so the runtime can fall back cleanly.
        """

    # ------------------------------------------------------------- helpers
    def _require_ready(self) -> None:
        st = self.status()
        if not st.usable:
            raise ProviderUnavailable(
                f"{self.display_name}: {st.detail}. "
                + (st.install_hint or st.credential_hint)
            )


def blocker(
    *, sdk_ok: bool, creds_ok: bool, needs_creds: bool,
    sdk_name: str, install_extra: str, credential_env: tuple[str, ...] = (),
    offline: bool = False,
) -> str:
    """The one specific reason a backend is unusable, with the fix.

    Ordered by what the user must do first: install the SDK, then supply
    credentials, then wait for the device to come back online.
    """
    if not sdk_ok:
        extra = f" (pip install 'quantum-os[{install_extra}]')" if install_extra else ""
        return f"{sdk_name} not installed{extra}"
    if needs_creds and not creds_ok:
        env = " or ".join(credential_env)
        return f"no credentials: set {env}" if env else "no credentials configured"
    if offline:
        return "device reported offline or unreachable"
    return ""


class ProviderUnavailable(RuntimeError):
    """Raised when a provider cannot execute for environmental reasons.

    Signals the runtime to try the next fallback in the plan rather than
    failing the whole job.
    """


class ProviderExecutionError(RuntimeError):
    """Raised when a provider was reachable but the run itself failed."""
