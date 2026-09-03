"""AssetRouter — reuse-before-generate decision for every shot.

Priority order:
1. Semantic Asset Library (reuse)
2. Existing project asset (reuse)
3. Licensed Stock
4. Generated Image
5. Image-to-Video
6. Text-to-Video
7. Premium video model
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..domain.asset import Asset
from ..domain.enums import GenerationStrategy
from ..domain.shot import ShotSpec
from .library import AssetLibrary
from .stock import StockProvider


@dataclass
class RouteDecision:
    action: str  # reuse_library | reuse_project | stock | generate
    plan: GenerationStrategy
    asset_id: Optional[str] = None
    asset: Optional[Asset] = None
    reason: str = ""
    similarity: float = 0.0


class AssetRouter:
    def __init__(
        self,
        library: AssetLibrary,
        stock: Optional[StockProvider] = None,
        threshold: float = 0.55,
    ) -> None:
        self.library = library
        self.stock = stock or StockProvider()
        self.threshold = threshold

    def route(self, shot: ShotSpec, project_id: str = "", query: str = "") -> RouteDecision:
        q = query or (shot.subject + " " + shot.action).strip()
        # 1 + 2: semantic library / same-project reuse
        best = self.library.best(q, self.threshold, project_id=project_id)
        if best is not None:
            action = "reuse_project" if best.project_id == project_id else "reuse_library"
            self.library.repo.increment_reuse(best.asset_id)
            return RouteDecision(
                action=action, plan=GenerationStrategy.REUSE_FROM_LIBRARY,
                asset_id=best.asset_id, asset=best,
                reason=f"reuse: similarity >= {self.threshold}", similarity=1.0,
            )
        # 3: licensed stock
        if shot.generation_strategy == GenerationStrategy.STOCK:
            stock_hits = self.stock.search(q)
            if stock_hits:
                a = stock_hits[0]
                return RouteDecision(
                    action="stock", plan=GenerationStrategy.STOCK,
                    asset_id=a.asset_id, asset=a, reason="licensed stock",
                )
        # 4-7: generation plan, cheapest viable first
        plan = self._generation_plan(shot)
        return RouteDecision(
            action="generate", plan=plan,
            reason=f"no library/stock match; plan={plan.value}",
        )

    @staticmethod
    def _generation_plan(shot: ShotSpec) -> GenerationStrategy:
        # Respect explicit provider/higher-tier constraints; otherwise cheapest viable.
        prefer = shot.generation_strategy
        if prefer in (
            GenerationStrategy.GENERATED_IMAGE,
            GenerationStrategy.IMAGE_TO_VIDEO,
            GenerationStrategy.TEXT_TO_VIDEO,
        ):
            # image+r's motion is cheaper than full text-to-video; honour the shot tier.
            return prefer
        return GenerationStrategy.IMAGE_TO_VIDEO
