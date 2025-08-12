# HedgeRunner 策略逻辑说明

## 开仓逻辑
- 每个 symbol 监控价差（spread = okx_price - bybit_price）/ bybit_price。
- 当没有持仓（`self.status[symbol] is None`）：
    - 如果 spread ≥ open_spread：
        - okx 开空（open_short），bybit 开多（open_long）。
        - 记录持仓状态为 "open"，方向为 1（`self.open_direction[symbol] = 1`）。
    - 如果 spread ≤ -open_spread：
        - okx 开多（open_long），bybit 开空（open_short）。
        - 记录持仓状态为 "open"，方向为 -1（`self.open_direction[symbol] = -1`）。

## 平仓逻辑
- 当已持仓（`self.status[symbol] == "open"`）：
    - 如果方向为 1 且 spread < close_spread：
        - okx 平空（close_short），bybit 平多（close_long）。
        - 清空持仓状态和方向。
    - 如果方向为 -1 且 spread > close_spread：
        - okx 平多（close_long），bybit 平空（close_short）。
        - 清空持仓状态和方向。

## 伪代码示例
```python
if pos_status is None:
    if spread >= open_spread:
        okx.open_short()
        bybit.open_long()
        status = "open"
        open_direction = 1
    elif spread <= -open_spread:
        okx.open_long()
        bybit.open_short()
        status = "open"
        open_direction = -1
elif pos_status == "open":
    if open_direction == 1 and spread < close_spread:
        okx.close_short()
        bybit.close_long()
        status = None
        open_direction = None
    elif open_direction == -1 and spread > close_spread:
        okx.close_long()
        bybit.close_short()
        status = None
        open_direction = None
```

---

