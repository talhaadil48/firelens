"""Cached hourly PSI catalogue check behind /meta (CLAUDE.md rule 5).

Requests never wait on PSI: /meta returns the last result and, when it is older than the
interval, starts one background refresh. Uses only the fast catalogue search endpoint.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from harvest.psi import BASE_URL, CATALOGUE_PARAMS, CATALOGUE_PATH, USER_AGENT

log = logging.getLogger("firelens.freshness")


@dataclass
class CatalogueCheck:
    interval_seconds: int
    enabled: bool = True
    checked_at: datetime | None = None
    new_accessions: list[str] = field(default_factory=list)
    _last_attempt: float = float("-inf")
    _running: bool = False

    def status(self, known: set[str]) -> tuple[datetime | None, list[str]]:
        if self.enabled and not self._running:
            if time.monotonic() - self._last_attempt > self.interval_seconds:
                self._last_attempt = time.monotonic()
                self._running = True
                threading.Thread(target=self._refresh, args=(known,), daemon=True).start()
        return self.checked_at, list(self.new_accessions)

    def _refresh(self, known: set[str]) -> None:
        try:
            with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
                response = client.get(BASE_URL + CATALOGUE_PATH, params=CATALOGUE_PARAMS)
                response.raise_for_status()
            hits = response.json().get("hits", {}).get("hits", [])
            current = {
                h["_source"]["Accession"]
                for h in hits
                if h.get("_source", {}).get("Research Area") == "Combustion Science"
            }
            self.new_accessions = sorted(current - known)
            self.checked_at = datetime.now(UTC)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("PSI catalogue check failed: %s", type(exc).__name__)
        finally:
            self._running = False
