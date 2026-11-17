"""The one place that loads Ultralytics YOLO. Its anonymous usage events (on by default in the user's global
settings) are switched off for this process only; the settings file is not touched."""

from __future__ import annotations


def YOLO(*args, **kwargs):  # noqa: N802 - mirrors ultralytics.YOLO
    from ultralytics import YOLO as _YOLO
    from ultralytics.utils import events

    events.events.enabled = False
    return _YOLO(*args, **kwargs)
