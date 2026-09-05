"""Quality control: technical (ffprobe/ffmpeg) + semantic/visual (multimodal)."""
from .technical import TechnicalQA
from .visual import MockVisualQA, VisualQAProvider

__all__ = ["TechnicalQA", "MockVisualQA", "VisualQAProvider"]
