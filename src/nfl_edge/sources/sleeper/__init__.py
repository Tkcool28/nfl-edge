"""Sleeper NFL public-API client for the bounded QB source audit.

The Sleeper public API is documented at https://docs.sleeper.com/. It is
read-only, requires no API key, and is subject to a soft limit of "stay
under 1000 API calls per minute". The single endpoint used by this
audit is::

    GET https://api.sleeper.app/v1/players/nfl?position=QB&active=true

The response is a JSON object keyed by Sleeper ``player_id`` (a string).
Each value contains the documented fields needed for a QB evidence
audit (identity, team, depth chart, injury, practice, roster).

This client is **deliberately restricted**:

* Only the filtered active-QB endpoint is called.
* No unofficial HTML pages are scraped.
* No API key, OAuth, or other secret is read from the environment.
* No state is mutated on the remote side (the API is read-only).
* The audit harness preserves every raw payload byte-for-byte and is
  read-only on the local filesystem apart from writing to its own
  ``data/source_audits/sleeper_qb_v1/`` tree.
"""

from .client import (
    DEFAULT_ENDPOINT,
    DEFAULT_TIMEOUT_SECONDS,
    SleeperAuditError,
    SleeperFetchResult,
    fetch_active_qb_snapshot,
    fetch_attempts,
    parse_response_headers,
)

__all__ = [
    "DEFAULT_ENDPOINT",
    "DEFAULT_TIMEOUT_SECONDS",
    "SleeperAuditError",
    "SleeperFetchResult",
    "fetch_active_qb_snapshot",
    "fetch_attempts",
    "parse_response_headers",
]
