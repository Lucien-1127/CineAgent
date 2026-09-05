"""Phase 6 tests: Asset Library (dedup/embeddings/reuse) + AssetRouter priorities."""
import pytest

from cineagent.assets import (
    AssetLibrary,
    AssetRouter,
    StockProvider,
    TokenHashEmbedder,
)
from cineagent.domain import Asset, AssetSource, AssetType, GenerationStrategy, ShotSpec

EMB = TokenHashEmbedder(dim=64)


def _db():
    from cineagent.storage.database import Database
    from cineagent.storage.repositories import AssetRepo, ensure_schema
    d = Database(":memory:")
    ensure_schema(d)
    return AssetRepo(d)


def _asset(aid, uri, tags, hash=None, project_id=""):
    return Asset(
        asset_id=aid, project_id=project_id, source=AssetSource.LIBRARY,
        type=AssetType.VIDEO, uri=uri, tags=tags, hash=hash or "",
    )


def test_library_dedup_by_hash_increments_reuse():
    repo = _db()
    lib = AssetLibrary(repo, EMB)
    a1 = _asset("a1", "/tmp/hero.mp4", tags=["城市", "夜景"], hash="abc123")
    lib.add(a1)
    # same content hash, different id => deduped to existing
    a2 = _asset("a2", "/tmp/hero_x.mp4", tags=["城市", "夜景"], hash="abc123")
    returned = lib.add(a2)
    assert returned.asset_id == "a1"
    assert repo.find_by_hash("abc123").reuse_count == 1
    assert len(repo.assets_for("")) == 1


def test_library_semantic_search_finds_match_above_threshold():
    repo = _db()
    lib = AssetLibrary(repo, EMB)
    lib.add(_asset("a1", "/tmp/rainy_city.mp4", tags=["城市", "雨夜"]))
    hit = lib.best("雨夜 城市 夜景", threshold=0.3)
    assert hit is not None


def test_library_search_respects_threshold():
    repo = _db()
    lib = AssetLibrary(repo, EMB)
    lib.add(_asset("a1", "/tmp/cat.mp4", tags=["貓", "可愛"]))
    assert lib.best("雨夜 城市 夜景", threshold=0.9) is None


def test_library_search_does_not_duplicate_global_assets():
    repo = _db()
    lib = AssetLibrary(repo, EMB)
    lib.add(_asset("a1", "/tmp/cat.mp4", tags=["貓", "可愛"]))
    hits = lib.search("貓 可愛", threshold=0.0, project_id="")
    assert [asset.asset_id for asset, _ in hits] == ["a1"]


class FakeStock(StockProvider):
    name = "fake-stock"

    def __init__(self, asset):
        self._asset = asset

    def search(self, query, license_ok=None):
        return [self._asset]


def test_router_reuses_library_before_generating():
    repo = _db()
    lib = AssetLibrary(repo, EMB)
    lib.add(_asset("a1", "/tmp/rainy_city.mp4", tags=["城市", "雨夜"]))
    router = AssetRouter(lib, threshold=0.3)
    shot = ShotSpec(shot_id="s1", scene_id="sc1", subject="城市", action="下雨")
    d = router.route(shot, project_id="proj-1")
    assert d.action == "reuse_library"
    assert d.plan == GenerationStrategy.REUSE_FROM_LIBRARY


def test_router_generates_when_no_match():
    repo = _db()
    router = AssetRouter(AssetLibrary(repo, EMB), threshold=0.95)
    shot = ShotSpec(shot_id="s1", scene_id="sc1", subject="獨角獸", action="奔跑")
    d = router.route(shot, project_id="")
    assert d.action == "generate"
    assert d.plan in (GenerationStrategy.GENERATED_IMAGE, GenerationStrategy.IMAGE_TO_VIDEO)


def test_router_uses_stock_when_requested():
    stock_asset = _asset("stock1", "/tmp/.pexels/forest.mp4", tags=["森林"])
    router = AssetRouter(
        AssetLibrary(_db(), EMB), stock=FakeStock(stock_asset),
    )
    shot = ShotSpec(
        shot_id="s1", scene_id="sc1", subject="森林",
        generation_strategy=GenerationStrategy.STOCK,
    )
    d = router.route(shot, project_id="")
    assert d.action == "stock"
    assert d.asset.asset_id == "stock1"
