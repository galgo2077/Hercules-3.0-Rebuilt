import tomllib
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    weights: dict[str, float]
    leverage: float
    trade_size_pct: float
    take_profit_pct: float
    checkpoint_trail_pct: float
    short_trailing_stop_pct: float
    stop_loss_pct: float | None
    short_exit_on_bullish_trend: bool
    max_concurrent_shorts: int


@dataclass(frozen=True, slots=True)
class DataframeConfig:
    interval: str
    warmup_bars: int


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    start_date: str
    end_date: str
    assets: list[str]
    initial_cash: float
    minimum_free_equity: float
    max_gross_exposure: float
    allow_short: bool
    fee_rate: float
    slippage_rate: float


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str
    port: int
    mode: str


@dataclass(frozen=True, slots=True)
class HerculesConfig:
    portfolio: PortfolioConfig
    dataframe: DataframeConfig
    backtest: BacktestConfig
    server: ServerConfig


def _load_toml(name: str) -> dict:
    path = _ROOT / f"{name}.toml"
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with path.open("rb") as f:
        return tomllib.load(f)


def _validate_weights(weights: dict[str, float], source: str) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"{source}: portfolio weights sum to {total:.6f}, must be 1.0")
    if any(w < 0 for w in weights.values()):
        raise ValueError(f"{source}: portfolio weights must be non-negative")


def load() -> HerculesConfig:
    portfolio_raw = _load_toml("Portfolio")
    dataframe_raw = _load_toml("Dataframe")
    backtest_raw = _load_toml("Backtest")
    server_raw = _load_toml("Server")

    weights = portfolio_raw["allocation"]
    _validate_weights(weights, "Portfolio.toml")

    portfolio = PortfolioConfig(
        weights=weights,
        leverage=float(portfolio_raw["leverage"]),
        trade_size_pct=float(portfolio_raw["trade_size_pct"]),
        take_profit_pct=float(portfolio_raw["take_profit_pct"]),
        checkpoint_trail_pct=float(portfolio_raw["checkpoint_trail_pct"]),
        short_trailing_stop_pct=float(portfolio_raw["short_trailing_stop_pct"]),
        stop_loss_pct=portfolio_raw.get("stop_loss_pct"),
        short_exit_on_bullish_trend=bool(portfolio_raw["short_exit_on_bullish_trend"]),
        max_concurrent_shorts=int(portfolio_raw["max_concurrent_shorts"]),
    )

    dataframe = DataframeConfig(
        interval=dataframe_raw["interval"],
        warmup_bars=int(dataframe_raw["warmup_bars"]),
    )

    bt = backtest_raw
    backtest = BacktestConfig(
        start_date=bt["data"]["start_date"],
        end_date=bt["data"]["end_date"],
        assets=list(bt["data"]["assets"]),
        initial_cash=float(bt["capital"]["initial_cash"]),
        minimum_free_equity=float(bt["capital"]["minimum_free_equity"]),
        max_gross_exposure=float(bt["capital"]["max_gross_exposure"]),
        allow_short=bool(bt["capital"]["allow_short"]),
        fee_rate=float(bt["execution"]["fee_rate"]),
        slippage_rate=float(bt["execution"]["slippage_rate"]),
    )

    server = ServerConfig(
        host=server_raw.get("host", "127.0.0.1"),
        port=int(server_raw.get("port", 8765)),
        mode=server_raw.get("mode", "paper"),
    )

    return HerculesConfig(
        portfolio=portfolio,
        dataframe=dataframe,
        backtest=backtest,
        server=server,
    )
