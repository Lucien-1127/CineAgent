"""CineAgent v4 — three-layer closed-loop video pipeline.

Layers
------
A. reverse.py   Video reverse engineering: shot detection, keyframes,
                VLM beat-sheet extraction (framing / camera move / rhythm).
B. anchor.py    Character anchor + first/last-frame chaining plan.
C. gate.py      VLM gatekeeper that scores rendered frames against the
                anchor and forces a retry / escalate decision.

prompts.py keeps ``image_prompt`` (static composition) and ``motion_prompt``
(纯運鏡與動態) strictly separated; routing.py picks the healthiest model on
OrcaRouter / OpenRouter for each capability.
"""

__version__ = "4.0.0"
