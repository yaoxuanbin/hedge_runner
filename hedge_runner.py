import threading
import time
import json
import logging
from okxclient import OkxClient
from bybitclient import BybitClient
import concurrent.futures

def load_hedge_config(config_path="config.json"):
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("hedge", {})

def setup_logger():
    logger = logging.getLogger("hedge")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.handlers = []
    logger.addHandler(handler)
    return logger

class HedgeRunner:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.hedge_cfg = load_hedge_config(config_path)
        self.okx = OkxClient(config_path)
        self.bybit = BybitClient(config_path)
        self.symbols = list(self.hedge_cfg.keys())
        self.status = {symbol: None for symbol in self.symbols}  # None/"open"/"close"
        self.logger = setup_logger()

    def set_leverage(self):
        for symbol, cfg in self.hedge_cfg.items():
            okx_id = cfg["okx"]
            bybit_id = cfg["bybit"]
            self.logger.info(f"设置杠杆: {symbol} okx={okx_id} bybit={bybit_id} 杠杆=1")
            self.okx.set_leverage(okx_id, 1, "isolated")
            self.bybit.set_leverage(bybit_id, 1, 1)

    def init_positions(self):
        for symbol, cfg in self.hedge_cfg.items():
            okx_id = cfg["okx"]
            bybit_id = cfg["bybit"]
            okx_pos = self.okx.get_positions(okx_id)
            bybit_pos = self.bybit.get_positions(bybit_id)
            # 检查OKX多/空
            okx_long = okx_pos.get("Buy", 0) > 0
            okx_short = okx_pos.get("Sell", 0) > 0
            # 检查Bybit多/空
            bybit_long = bybit_pos and bybit_pos.get("Buy", 0) > 0
            bybit_short = bybit_pos and bybit_pos.get("Sell", 0) > 0
            # 只有一边多一边空才算有持仓
            has_pos = (okx_short and bybit_long) or (okx_long and bybit_short)
            self.status[symbol] = "open" if has_pos else None
            self.logger.info(f"初始化持仓: {symbol} 持仓状态: {'对冲持仓' if has_pos else '无仓'}")

    def monitor_symbol(self, symbol):
        cfg = self.hedge_cfg[symbol]
        okx_id = cfg["okx"]
        bybit_id = cfg["bybit"]
        open_spread = cfg.get("open_spread", 0.004)
        close_spread = cfg.get("close_spread", 0.0)
        qty = cfg.get("qty", 1)
        while True:
            try:
                okx_ticker = self.okx.get_ticker(okx_id)
                okx_price = float(okx_ticker["data"][0]["last"])
                bybit_price = float(self.bybit.get_ticker([bybit_id]).get(bybit_id))
                spread = (okx_price - bybit_price) / bybit_price
                self.logger.info(f"{symbol} okx: {okx_price}, bybit: {bybit_price}, spread: {spread*100:.3f}%")
                pos_status = self.status[symbol]
                # 开仓逻辑
                if pos_status is None:
                    if spread >= open_spread:
                        self.logger.info(f"{symbol} 价差大于{open_spread*100:.2f}%，okx开空，bybit开多")
                        okx_ret = self.okx.open_short(okx_id, qty)
                        bybit_ret = self.bybit.open_long(bybit_id, qty)
                        self.status[symbol] = "open"
                    elif spread <= -open_spread:
                        self.logger.info(f"{symbol} 价差小于-{open_spread*100:.2f}%，okx开多，bybit开空")
                        okx_ret = self.okx.open_long(okx_id, qty)
                        bybit_ret = self.bybit.open_short(bybit_id, qty)
                        self.status[symbol] = "open"
                # 平仓逻辑
                elif pos_status == "open":
                        if (direction == 1 and spread < close_spread) or (direction == -1 and spread > close_spread):
                            self.logger.info(f"{symbol} 价差满足平仓条件，平仓")
                            self.okx.close_long(okx_id)
                            self.okx.close_short(okx_id)
                            self.bybit.close_long(bybit_id)
                            self.bybit.close_short(bybit_id)
                            self.status[symbol] = None
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"{symbol} 监控异常: {e}")
                time.sleep(2)

    def fetch_all_prices(self):
        def fetch_okx(symbol, okx_id):
            try:
                ticker = self.okx.get_ticker(okx_id)
                if ticker and 'data' in ticker and ticker['data']:
                    return symbol, float(ticker['data'][0]['last'])
            except Exception as e:
                self.logger.error(f"OKX {symbol} 行情异常: {e}")
            return symbol, None

        def fetch_bybit(symbol, bybit_id):
            try:
                price = self.bybit.get_ticker([bybit_id]).get(bybit_id)
                if price:
                    return symbol, float(price)
            except Exception as e:
                self.logger.error(f"Bybit {symbol} 行情异常: {e}")
            return symbol, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.symbols)*2) as executor:
            okx_futures = {executor.submit(fetch_okx, s, self.hedge_cfg[s]['okx']): s for s in self.symbols}
            bybit_futures = {executor.submit(fetch_bybit, s, self.hedge_cfg[s]['bybit']): s for s in self.symbols}
            okx_prices = {future.result()[0]: future.result()[1] for future in concurrent.futures.as_completed(okx_futures)}
            bybit_prices = {future.result()[0]: future.result()[1] for future in concurrent.futures.as_completed(bybit_futures)}
        return okx_prices, bybit_prices

    def run(self):
        self.set_leverage()
        self.init_positions()
        self.logger.info("对冲监控已启动...")
        last_status = {symbol: None for symbol in self.symbols}
        while True:
            okx_prices, bybit_prices = self.fetch_all_prices()
            for symbol in self.symbols:
                cfg = self.hedge_cfg[symbol]
                okx_price = okx_prices.get(symbol)
                bybit_price = bybit_prices.get(symbol)
                if okx_price is None or bybit_price is None:
                    continue
                open_spread = cfg.get("open_spread", 0.004)
                close_spread = cfg.get("close_spread", 0.0)
                qty = cfg.get("qty", 1)
                spread = (okx_price - bybit_price) / bybit_price
                self.logger.info(f"{symbol} okx: {okx_price}, bybit: {bybit_price}, spread: {spread*100:.3f}%")
                pos_status = self.status[symbol]
                # 开仓逻辑
                if pos_status is None and last_status[symbol] != "open":
                    if spread >= open_spread:
                        self.logger.info(f"{symbol} 价差大于{open_spread*100:.2f}%，okx开空，bybit开多")
                        self.okx.open_short(cfg["okx"], qty)
                        self.bybit.open_long(cfg["bybit"], qty)
                        self.status[symbol] = "open"
                        last_status[symbol] = "open"
                    elif spread <= -open_spread:
                        self.logger.info(f"{symbol} 价差小于-{open_spread*100:.2f}%，okx开多，bybit开空")
                        self.okx.open_long(cfg["okx"], qty)
                        self.bybit.open_short(cfg["bybit"], qty)
                        self.status[symbol] = "open"
                        last_status[symbol] = "open"
                # 平仓逻辑
                elif pos_status == "open" and last_status[symbol] != None:
                    if abs(spread) <= close_spread:
                        self.logger.info(f"{symbol} 价差回归{close_spread*100:.2f}%以内，平仓")
                        self.okx.close_long(cfg["okx"])
                        self.okx.close_short(cfg["okx"])
                        self.bybit.close_long(cfg["bybit"])
                        self.bybit.close_short(cfg["bybit"])
                        self.status[symbol] = None
                        last_status[symbol] = None
            time.sleep(1)

if __name__ == "__main__":
    runner = HedgeRunner()
    runner.run()
