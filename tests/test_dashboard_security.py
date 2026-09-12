from pathlib import Path


def test_dashboard_has_no_html_injection_or_browser_token_storage() -> None:
    dashboard = Path(__file__).resolve().parents[1] / "dashboard"
    source = "\n".join(path.read_text(encoding="utf-8") for path in dashboard.glob("*") if path.suffix in {".html", ".js"})
    for forbidden in ("innerHTML", "localStorage", "sessionStorage", "access_token", "refresh_token"):
        assert forbidden not in source


def test_interval_is_sent_to_candle_endpoint() -> None:
    monitor = (Path(__file__).resolve().parents[1] / "dashboard" / "monitor.js").read_text(encoding="utf-8")
    assert "/api/candles?asset=${encodeURIComponent(asset)}&limit=200&interval=${encodeURIComponent(interval)}" in monitor


def test_dashboard_does_not_load_remote_scripts() -> None:
    dashboard = Path(__file__).resolve().parents[1] / "dashboard"
    html = "\n".join(path.read_text(encoding="utf-8") for path in dashboard.glob("*.html"))
    assert '<script src="http' not in html


def test_trade_table_has_status_filters_and_sorting() -> None:
    dashboard = Path(__file__).resolve().parents[1] / "dashboard"
    html = (dashboard / "index.html").read_text(encoding="utf-8")
    script = (dashboard / "monitor.js").read_text(encoding="utf-8")
    assert all(f'data-trade-filter="{value}"' in html for value in ("active", "closed", "all"))
    assert 'id="tradeSort"' in html
    assert "function isActive(trade)" in script
    assert ".sort(sorters[tradeSort]||sorters.newest)" in script
    assert all(f"<th>{label}</th>" in html for label in ("TP", "SL", "Liq.", "Lev.", "Source"))
    assert "actual fill markers" in html
    assert "/monitor.js?v=9" in html
    assert "entry → exit" in script
    assert "BUY':'SELL" in script
