"""Pick narratives: a deterministic template, optionally rephrased by Claude.

The template is the source of truth for the *numbers* — if an Anthropic key
is configured and ``use_ai`` is set, Claude is given the template text and
told to rewrite it without inventing new figures. If anything goes wrong
(missing key, network error), the template is returned as-is.
"""
from __future__ import annotations

import os
from typing import Any, Dict


def template_narrative(pick: Dict[str, Any]) -> str:
    side_word = "the over" if pick["side"] == "over" else "the under"
    noun = pick.get("statNoun", "strikeouts")
    parts = [
        f"{pick['player']} projects to {pick['projection']:.1f} {noun}, "
        f"which favors {side_word} {pick['line']}."
    ]

    for s in pick["splits"]:
        if s["n"] > 0 and not s["label"].startswith("Current streak"):
            parts.append(f"{s['label']}: {s['hits']}/{s['n']} ({s['rate'] * 100:.0f}%).")
        if len(parts) >= 4:
            break

    streak = next((s for s in pick["splits"] if s["label"].startswith("Current streak")), None)
    if streak:
        parts.append(f"{streak['label']}.")

    edge = pick.get("edge")
    if edge:
        if edge["evPct"] > 0:
            parts.append(
                f"At {edge['price']:+d}, that's +{edge['evPct']:.1f}% EV "
                f"(model {edge['modelProb'] * 100:.0f}% vs. fair {edge['fairProb'] * 100:.0f}%); "
                f"Kelly suggests {edge['kellyPct']:.1f}% of bankroll (consider ~1/4 of that)."
            )
        else:
            parts.append(
                f"At {edge['price']:+d}, the model doesn't beat the market "
                f"({edge['evPct']:.1f}% EV) — pass on this number."
            )
    else:
        parts.append("No live line was matched, so this is analysis only, not a betting edge.")

    if pick.get("lowSample"):
        parts.append("Sample size is still small this season, so treat the edges loosely.")

    return " ".join(parts)


async def generate_narrative(pick: Dict[str, Any], use_ai: bool) -> str:
    base = template_narrative(pick)
    if not use_ai:
        return base

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return base

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        prompt = (
            "Rewrite the following sports-betting model output as a short, natural "
            "paragraph for a sharp bettor. Use ONLY the numbers given below — do not "
            "invent or change any figures, and do not promise an outcome. Keep it under "
            "80 words.\n\n" + base
        )
        resp = await client.messages.create(
            model=model,
            max_tokens=220,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(block, "text", "") for block in resp.content).strip()
        return text or base
    except Exception:
        return base
