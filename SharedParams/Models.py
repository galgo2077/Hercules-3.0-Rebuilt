from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    LONG = "Long"
    SHORT = "Short"
    NONE = "None"


class Action(str, Enum):
    HOLD = "Hold"
    ENTRY = "Entry"
    ADJUST = "Adjust"
    EXIT = "Exit"


@dataclass(frozen=True, slots=True)
class BuildResult:
    timestamp: datetime
    asset: str
    action: Action
    side: Side
    target_exposure: float
    exposure_delta: float
    entry_allowed: bool
    exit_required: bool
    reason: str
