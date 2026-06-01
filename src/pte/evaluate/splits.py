from datetime import datetime, timedelta


def time_split(
    records: list[dict],
    ts_field: str = "created_ts",
    holdout_days: int = 30,
) -> tuple[list[dict], list[dict]]:
    """Split records by time: train on earlier portion, test on holdout tail."""
    parsed = []
    for r in records:
        ts_str = r.get(ts_field)
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str[:10])
                parsed.append((ts, r))
            except ValueError:
                continue

    if not parsed:
        return [], []

    max_ts = max(ts for ts, _ in parsed)
    cutoff = max_ts - timedelta(days=holdout_days)

    train = [r for ts, r in parsed if ts <= cutoff]
    test = [r for ts, r in parsed if ts > cutoff]
    return train, test


def rolling_window_split(
    records: list[dict],
    ts_field: str = "created_ts",
    window_days: int = 90,
    step_days: int = 30,
) -> list[tuple[list[dict], list[dict]]]:
    """Generate (train, test) windows for rolling-window backtest."""
    parsed = sorted(
        [(datetime.fromisoformat(r.get(ts_field, "2020-01-01")[:10]), r) for r in records],
        key=lambda x: x[0],
    )
    if not parsed:
        return []

    splits = []
    min_ts = parsed[0][0]
    max_ts = parsed[-1][0]
    cursor = min_ts + timedelta(days=window_days)

    while cursor <= max_ts:
        train_start = cursor - timedelta(days=window_days)
        train = [r for ts, r in parsed if train_start <= ts < cursor - timedelta(days=step_days)]
        test = [r for ts, r in parsed if cursor - timedelta(days=step_days) <= ts < cursor]
        if train and test:
            splits.append((train, test))
        cursor += timedelta(days=step_days)
    return splits
