"""Stock provider abstraction. Status: `planned` (no adapter yet).

Stock search is invoked only when the local library has no good match, per the
reuse-first priority. A missing/empty stock adapter degrades gracefully to
'no stock' and the router moves to generation.
"""
from __future__ import annotations

from typing import List, Optional

from ..domain.asset import Asset


class StockUnavailable(RuntimeError):
    """Stock backend not configured or declined the query."""


class StockProvider:
    name = "stock-null"

    def search(self, query: str, license_ok: Optional[str] = None) -> List[Asset]:
        """Return licensed stock assets for `query`. Default: none.

        Adapters (Pexels/Pixabay/etc.) implement real lookup behind this.
        """
        return []
