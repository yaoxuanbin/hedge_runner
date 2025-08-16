import threading
import time
import json
from okxclient import OkxClient
from bybitclient import BybitClient

def load_hedge_config(config_path="config.json"):
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("hedge", {})

class HedgeRunner:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.hedge_cfg = load_hedge_config(config_path)
        self.okx = OkxClient(config_path)
        self.bybit = BybitClient(config_path)
        self.symbols = list(self.hedge_cfg.keys())
        self.status = {symbol: None for symbol in self.symbols}  # None/"open"/"close"

    def set_leverage(self):
        for symbol, cfg in self.hedge_cfg.items():
            okx_id = cfg["okx"]
            bybit_id = cfg["bybit"]
            self.okx.set_leverage(okx_id, 1, "isolated")
            self.bybit.set_leverage(bybit_id, 1, 1)

    def init_positions(self):
        self.open_direction = {}  # 1=正向，-1=反向，None=无持仓
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
            # 判断方向
            if okx_short and bybit_long:
                self.open_direction[symbol] = 1  # 正向：okx空bybit多
            elif okx_long and bybit_short:
                self.open_direction[symbol] = -1  # 反向：okx多bybit空
            else:
                self.open_direction[symbol] = None
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 初始化持仓: {symbol} 持仓状态: {'对冲持仓' if has_pos else '无仓'}，方向: {self.open_direction[symbol]}")
            
    def fetch_all_prices(self):
        okx_prices = {}
        bybit_prices = {}
        for symbol in self.symbols:
            okx_id = self.hedge_cfg[symbol]['okx']
            bybit_id = self.hedge_cfg[symbol]['bybit']

            # OKX价格用OKX symbol查
            try:
                okx_price = self.okx.get_ticker(okx_id).get(okx_id)
            except Exception as e:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 获取OKX {symbol} 行情失败: {e}")
                okx_price = None
                
            # Bybit价格用Bybit symbol查
            try:
                bybit_price = self.bybit.get_ticker([bybit_id]).get(bybit_id)
            except Exception as e:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 获取Bybit {symbol} 行情失败: {e}")
                bybit_price = None
            # test start
            # bybit_price=okx_price
            # test end
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} OKX {symbol} 行情: {okx_price}")
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Bybit {symbol} 行情: {bybit_price}")
            
            if okx_price:
                okx_prices[symbol] = float(okx_price)
            else:
                okx_prices[symbol] = None
            
            if bybit_price:
                bybit_prices[symbol] = float(bybit_price)
            else:
                bybit_prices[symbol] = None

        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} OKX价格: {okx_prices}")
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Bybit价格: {bybit_prices}")
        return okx_prices, bybit_prices

    def run(self):
        self.set_leverage()
        self.init_positions()
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 对冲监控已启动...")
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
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {symbol} okx: {okx_price}, bybit: {bybit_price}, spread: {spread*100:.3f}%")
                pos_status = self.status[symbol]
                direction = self.open_direction.get(symbol)
                # 开仓逻辑
                if pos_status is None:
                    if spread >= open_spread:
                        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {symbol} 价差大于{open_spread*100:.2f}%，okx开空，bybit开多")
                        self.okx.open_short(cfg["okx"], qty)
                        self.bybit.open_long(cfg["bybit"], qty)
                        self.status[symbol] = "open"
                        self.open_direction[symbol] = 1
                    elif spread <= -open_spread:
                        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {symbol} 价差小于-{open_spread*100:.2f}%，okx开多，bybit开空")
                        self.okx.open_long(cfg["okx"], qty)
                        self.bybit.open_short(cfg["bybit"], qty)
                        self.status[symbol] = "open"
                        self.open_direction[symbol] = -1
                # 平仓逻辑
                elif pos_status == "open":
                    if direction == 1 and spread <= close_spread:
                        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {symbol} 正向持仓，价差回归，平仓")
                        self.okx.close_short(cfg["okx"])
                        self.bybit.close_long(cfg["bybit"])
                        self.status[symbol] = None
                        self.open_direction[symbol] = None
                    elif direction == -1 and spread >= close_spread:
                        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {symbol} 反向持仓，价差回归，平仓")                    
                        self.okx.close_long(cfg["okx"])
                        self.bybit.close_short(cfg["bybit"])
                        self.status[symbol] = None
                        self.open_direction[symbol] = None
            time.sleep(1)


if __name__ == "__main__":
    runner = HedgeRunner()
    runner.run()
