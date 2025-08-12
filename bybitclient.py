
import os
from pybit.unified_trading import HTTP
import json
import uuid
import datetime

class BybitClient:
    def __init__(self, config_path="config.json"):
        config_path = os.path.join(os.path.dirname(__file__), config_path)
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        bybit_cfg = config.get("bybit", {})
        self.api_key = bybit_cfg.get("api_key", "")
        self.secret_key = bybit_cfg.get("secret_key", "")
        self.sim_mode = config.get("sim_mode", True)
        self.session = HTTP(
            testnet=self.sim_mode,
            api_key=self.api_key,
            api_secret=self.secret_key,
        )

    def get_ticker(self, symbols, category="linear"):
        """
        获取多个币种的最新价格。
        :param symbols: 币种列表，如 ["BTCUSDT", "ETHUSDT"]
        :param category: 合约类型，默认"linear"
        :return: dict，键为币种，值为最新价（失败时为None）
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        result = self.session.get_tickers(category=category)
        prices = {symbol: None for symbol in symbols}
        if result.get("retCode") == 0:
            for ticker in result["result"]["list"]:
                if ticker["symbol"] in symbols:
                    try:
                        prices[ticker["symbol"]] = float(ticker["lastPrice"])
                    except Exception:
                        prices[ticker["symbol"]] = None
                    print(f"{ticker['symbol']} 最新价: {ticker['lastPrice']}")
        else:
            print("获取价格失败:", result)
        return prices

    def create_perp_market_order(self, symbol, side, qty, category="linear"):
        orderLinkId = uuid.uuid4().hex
        result = self.session.place_order(
            category=category,
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),
            orderLinkId=orderLinkId,
            positionIdx=1 if side == "Buy" else 2
        )
        if result.get("retCode") == 0:
            print(f"{symbol} {side} 市价单下单成功，订单ID: {result['result']['orderId']}")
            return True
        else:
            print(f"{symbol} {side} 市价单下单失败:", result)
            return False
    
    def switch_to_hedge_mode(self, symbol, category="linear"):
        try:
            return self.session.switch_position_mode(
                category=category,
                symbol=symbol,
                mode=3  # 3=双向持仓，1=单向持仓
            )
        except Exception as e:
            print("切换到对冲模式失败:", e)
            return {"retCode": 1, "retMsg": str(e)}

    def swap_trade(self, symbol, side, qty, positionIdx, category="linear"):
        """
        平仓：side为"Buy"时平空，side为"Sell"时平多，qty为平仓数量，positionIdx需对应方向
        """
        orderLinkId = uuid.uuid4().hex
        result = self.session.place_order(
            category=category,
            symbol=symbol,
            side=side,  # "Buy" 平空, "Sell" 平多
            orderType="Market",
            qty=str(qty),
            reduceOnly=True,
            orderLinkId=orderLinkId,
            positionIdx=str(positionIdx)  # 1=平多, 2=平空，必须为字符串
        )
        print("平仓返回：", result)
        return result


    def get_positions(self, symbol, category="linear"):
        """
        获取指定合约的多头和空头持仓量
        :return: dict, 例如 {"Buy": 0.001, "Sell": 0.002}
        """
        result = self.session.get_positions(category=category, symbol=symbol)
        sizes = {"Buy": 0.0, "Sell": 0.0}
        if result.get("retCode") == 0:
            positions = result["result"].get("list", [])
            for pos in positions:
                side = pos.get("side")
                size = float(pos.get("size", 0))
                if side in sizes:
                    sizes[side] = size
            print(f"{symbol} 持仓量: {sizes}")
            return sizes
        else:
            print("获取持仓失败:", result)
            return None
        
    def open_long(self, symbol, qty, category="linear"):
            """开多仓（买入开仓）"""
            print(f"[{datetime.datetime.now()}] 开多仓 {symbol} Buy {qty}")
            # 开多用Buy，positionIdx=1
            result = self.create_perp_market_order(symbol, "Buy", qty, category=category)
            return result

    def open_short(self, symbol, qty, category="linear"):
        """开空仓（卖出开仓）"""
        print(f"[{datetime.datetime.now()}] 开空仓 {symbol} Sell {qty}")
        # 开空用Sell，positionIdx=2
        result = self.create_perp_market_order(symbol, "Sell", qty, category=category)
        return result
    
    def close_long(self, symbol, category="linear"):
        """平掉指定合约的多头持仓"""
        positions = self.session.get_positions(category=category, symbol=symbol)
        if positions.get("retCode") != 0:
            print(f"[{datetime.datetime.now()}] 查询持仓失败: {positions}")
            return None, False
        pos_list = positions["result"].get("list", [])
        long_pos = None
        for pos in pos_list:
            if pos.get("side") == "Buy" and float(pos.get("size", 0)) > 0:
                long_pos = pos
                break
        if not long_pos:
            print(f"[{datetime.datetime.now()}] 无多头持仓可平: {symbol}")
            return None, False
        qty = float(long_pos["size"])
        print(f"[{datetime.datetime.now()}] 平多仓 {symbol} Buy {qty}")
        # 平多用Sell，positionIdx=1
        result = self.swap_trade(symbol, "Sell", qty, 1, category=category)
        return result, True

    def close_short(self, symbol, category="linear"):
        """平掉指定合约的空头持仓"""
        positions = self.session.get_positions(category=category, symbol=symbol)
        if positions.get("retCode") != 0:
            print(f"[{datetime.datetime.now()}] 查询持仓失败: {positions}")
            return None, False
        pos_list = positions["result"].get("list", [])
        short_pos = None
        for pos in pos_list:
            if pos.get("side") == "Sell" and float(pos.get("size", 0)) > 0:
                short_pos = pos
                break
        if not short_pos:
            print(f"[{datetime.datetime.now()}] 无空头持仓可平: {symbol}")
            return None, False
        qty = float(short_pos["size"])
        print(f"[{datetime.datetime.now()}] 平空仓 {symbol} Sell {qty}")
        # 平空用Buy，positionIdx=2
        result = self.swap_trade(symbol, "Buy", qty, 2, category=category)
        return result, True

    def set_leverage(self, symbol, buy_leverage=1, sell_leverage=1, category="linear"):
        try:
            return self.session.set_leverage(
                category=category,
                symbol=symbol,
                buyLeverage=str(buy_leverage),
                sellLeverage=str(sell_leverage)
            )
        except Exception as e:
            print("设置杠杆失败:", e)
            return {"retCode": 1, "retMsg": str(e)}

if __name__ == "__main__":
    bybit = BybitClient()
    bybit.set_leverage("BTCUSDT", 1, 1)
    bybit.set_leverage("ETHUSDT", 1, 1)
    bybit.switch_to_hedge_mode("ETHUSDT")
    # bybit.open_long("BTCUSDT", 0.001)
    print(bybit.get_ticker(["BTCUSDT", "DOGEUSDT"]))

    # bybit.get_positions("BTCUSDT")