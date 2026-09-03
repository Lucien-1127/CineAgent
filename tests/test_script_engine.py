"""Phase 3 tests: Script Engine + PromptCompiler (via MockTextProvider)."""
import asyncio

import pytest

from cineagent.creative import PromptCompiler, ScriptEngine, VendorNotImplemented
from cineagent.domain import (
    CreativeBrief,
    HookCandidate,
    HookSet,
    ScriptPackage,
    ShotSpec,
)
from cineagent.domain.script import CritiqueResult
from cineagent.providers.text.mock import MockTextProvider


def _run(coro):
    return asyncio.run(coro)


def _valid_brief():
    return {
        "audience": "大眾",
        "core_message": "AI 讓創作更快",
        "emotional_goal": "啟發",
        "content_type": "短影音",
        "references": [],
        "prohibited_elements": ["血腥"],
        "cta_strategy": "追蹤",
    }


def _valid_hooks():
    return HookSet(candidates=[
        HookCandidate(text="hook-low", score=0.3),
        HookCandidate(text="hook-mid", score=0.6),
        HookCandidate(text="hook-top", score=0.9),
    ])


def _valid_script():
    return {
        "hook": "hook-top",
        "narration": "第一幕。第二幕。",
        "scenes": [
            {"scene_id": "s1", "narration": "第一幕。", "title": "開場", "goal": "吸引"},
            {"scene_id": "s2", "narration": "第二幕。", "title": "主體", "goal": "說明"},
        ],
        "facts": [],
        "cta": "追蹤我",
        "metadata": {},
        "script_strategy": "short_viral",
        "expected_duration": 10.0,
        "platform": "shorts",
    }


def _make_provider(script_dicts=None, hooks=None, critique_passed=True):
    provider = MockTextProvider()
    remaining = list(script_dicts) if script_dicts else None

    def handler(schema):
        if schema is CreativeBrief:
            return _valid_brief()
        if schema is HookSet:
            return hooks if hooks is not None else {"candidates": []}
        if schema is CritiqueResult:
            return {"passed": critique_passed, "notes": [], "revision_guidance": ""}
        if schema is ScriptPackage:
            if remaining:
                return remaining.pop(0)
            return _valid_script()
        raise AssertionError(f"unexpected schema {schema}")

    provider.handler = handler
    return provider


def _provider_with_critique(results):
    provider = MockTextProvider()
    queue = list(results)

    def handler(schema):
        if schema is CreativeBrief:
            return _valid_brief()
        if schema is HookSet:
            return _valid_hooks()
        if schema is ScriptPackage:
            return _valid_script()
        if schema is CritiqueResult:
            if not queue:
                return {"passed": True, "notes": [], "revision_guidance": ""}
            return {"passed": queue.pop(0), "notes": ["改進"], "revision_guidance": "再來"}
        raise AssertionError(schema)

    provider.handler = handler
    return provider


def test_engine_picks_best_hook_and_returns_package():
    engine = ScriptEngine()
    provider = _make_provider(hooks=_valid_hooks())
    pkg = _run(engine.run(provider, "測試主題"))
    assert isinstance(pkg, ScriptPackage)
    assert pkg.hook == "hook-top"
    assert len(engine.last_critiques) == 1


def test_malformed_json_raises_not_accepted_as_free_text():
    engine = ScriptEngine()
    provider = MockTextProvider()
    provider.malformed_next = True
    provider.handler = lambda schema: _valid_brief()
    with pytest.raises(ValueError):
        _run(engine.run(provider, "主題"))


def test_injected_rate_limit_propagates():
    engine = ScriptEngine()
    provider = MockTextProvider()
    from cineagent.providers.base import RateLimitError
    provider.fail_next = RateLimitError("429 throttled")
    provider.handler = lambda schema: _valid_brief()
    with pytest.raises(RateLimitError):
        _run(engine.run(provider, "主題"))


def test_critic_loop_regenerates_until_pass():
    engine = ScriptEngine()
    provider = _provider_with_critique([False, True])
    pkg = _run(engine.run(provider, "主題"))
    assert pkg is not None
    assert engine.last_critiques[0].passed is False
    assert engine.last_critiques[1].passed is True


def test_fact_check_skipped_for_short_viral():
    from cineagent.creative import ScriptCritic
    from cineagent.domain import ScriptStrategy
    critic = ScriptCritic()
    assert critic.needs_fact_check(ScriptStrategy.SHORT_VIRAL) is False


def test_prompt_compiler_default_and_vendor_gate():
    shot = ShotSpec(shot_id="shot-1", scene_id="s1", subject="城市", action="下雨")
    pc = PromptCompiler()
    payload = pc.compile(shot, "agnostic")
    assert "城市" in payload["prompt_text"]
    with pytest.raises(VendorNotImplemented):
        pc.compile(shot, "veo")
