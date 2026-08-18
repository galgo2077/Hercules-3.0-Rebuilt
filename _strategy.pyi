class StrategyInput:
    timestamp_ms: int
    asset: str
    direction: str | None
    final_signal: int
    short_trend_similarity: float
    slope: float
    warmup_complete: bool
    def __init__(
        self,
        timestamp_ms: int,
        asset: str,
        direction: str | None,
        final_signal: int,
        short_trend_similarity: float,
        slope: float,
        warmup_complete: bool,
    ) -> None: ...

class BuildResult:
    timestamp_ms: int
    asset: str
    action: str
    side: str
    target_exposure: float
    exposure_delta: float
    entry_allowed: bool
    exit_required: bool
    reason: str

def evaluate(input: StrategyInput, current_side: int, require_slope_confirmation: bool) -> tuple[float, float]: ...
def build_decision(
    timestamp_ms: int,
    asset: str,
    long_score: float,
    short_score: float,
    current_exposure: float,
    target_long: float,
    target_short: float,
) -> BuildResult: ...
