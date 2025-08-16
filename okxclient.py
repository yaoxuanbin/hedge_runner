import okx.Account as Account
import okx.Trade as Trade
import okx.MarketData as MarketData
from datetime import datetime
import json
import os
import time



class OkxClient:
    def __init__(self, config_path="config.json"):
        config_path = os.path.join(os.path.dirname(__file__), config_path)
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        okx_cfg = config.get("okx", {})
        sim_mode = config.get("sim_mode", False)
        self.api_key = okx_cfg.get("api_key", "")
        self.secret_key = okx_cfg.get("secret_key", "")
        self.passphrase = okx_cfg.get("passphrase", "")
        self.sim_mode = sim_mode
        self.trade_api = Trade.TradeAPI(self.api_key, self.secret_key, self.passphrase, False, "1" if self.sim_mode else "0")
        self.market_api = MarketData.MarketAPI(self.api_key, self.secret_key, self.passphrase, False, "1" if self.sim_mode else "0")
        self.account_api = Account.AccountAPI(self.api_key, self.secret_key, self.passphrase, False, "1" if self.sim_mode else "0")

    def get_ticker(self, inst_id):
        """
        获取最新行情，支持单个或多个合约ID。
        返回: {symbol: 最新价float} 的dict，和BybitClient一致。
        """
        result = {}
        if isinstance(inst_id, str):
            ticker = self.market_api.get_ticker(inst_id)
            if ticker and ticker.get("code") == "0" and ticker.get("data"):
                try:
                    result[inst_id] = float(ticker["data"][0]["last"])
                except Exception:
                    result[inst_id] = None
            else:
                result[inst_id] = None
            return result
        elif isinstance(inst_id, (list, tuple)):
            for iid in inst_id:
                ticker = self.market_api.get_ticker(iid)
                if ticker and ticker.get("code") == "0" and ticker.get("data"):
                    try:
                        result[iid] = float(ticker["data"][0]["last"])
                    except Exception:
                        result[iid] = None
                else:
                    result[iid] = None
            return result
        else:
            raise ValueError("inst_id 必须为 str 或 list/tuple[str]")

    def get_positions(self, inst_id, category=None):
        """
        获取指定合约的多头和空头持仓量，返回dict: {"Buy": float, "Sell": float}
        """
        result = self.account_api.get_positions(instType="SWAP")
        sizes = {"Buy": 0.0, "Sell": 0.0}
        if result and result.get("code") == "0":
            positions = result.get("data", [])
            for pos in positions:
                if pos.get("instId") != inst_id:
                    continue
                # OKX: posSide=="long" 视为Buy, posSide=="short" 视为Sell
                if pos.get("posSide") == "long":
                    try:
                        sizes["Buy"] = float(pos.get("availPos", 0))
                    except Exception:
                        sizes["Buy"] = 0.0
                elif pos.get("posSide") == "short":
                    try:
                        sizes["Sell"] = float(pos.get("availPos", 0))
                    except Exception:
                        sizes["Sell"] = 0.0
            return sizes
        else:
            return sizes

    def swap_trade(self, inst_id, side, amount, price=None, posSide="short"):
        """永续合约交易（支持指定价格）"""
        try:
            params = {
                "instId": inst_id,
                "tdMode": "isolated",
                "side": side,
                "ordType": "limit" if price else "market",
                "sz": str(amount),
                "posSide": posSide
            }
            if price:
                params["px"] = str(price)
            print(f"[{datetime.now()}] 提交合约{side}订单: {params}")
            result = self.trade_api.place_order(**params)
            if result['code'] != '0':
                print(f"[{datetime.now()}] 合约{side}订单失败: {result.get('code')}")
                print(f"[{datetime.now()}] 合约{side}订单失败: {result.get('msg')}")
                return None, False

            ord_id = result['data'][0]['ordId']
            return ord_id, False
        except Exception as e:
            print(f"[{datetime.now()}] 合约{side}交易失败: {str(e)}")
            return None, False

        print(f"[{datetime.now()}] 平仓 {inst_id} {pos_side} {avail_pos} 张")
        return self.swap_trade(inst_id=inst_id, side=side, amount=avail_pos, price=None, posSide=pos_side)

    def open_long(self, inst_id, amount, price=None):
        """开多仓（买入开多）"""
        print(f"[{datetime.now()}] 开多仓 {inst_id} long {amount} 张")
        return self.swap_trade(inst_id=inst_id, side="buy", amount=amount, price=price, posSide="long")

    def open_short(self, inst_id, amount, price=None):
        """开空仓（卖出开空）"""
        print(f"[{datetime.now()}] 开空仓 {inst_id} short {amount} 张")
        return self.swap_trade(inst_id=inst_id, side="sell", amount=amount, price=price, posSide="short")

    def close_long(self, inst_id):
        """平掉指定SWAP合约的多头持仓"""
        positions = self.get_positions(inst_id)
        qty = positions.get("Buy", 0.0)
        if qty <= 0:
            print(f"[{datetime.now()}] 无多头持仓可平: {inst_id}")
            return None, False
        print(f"[{datetime.now()}] 平多仓 {inst_id} long {qty} 张")
        return self.swap_trade(inst_id=inst_id, side="sell", amount=qty, price=None, posSide="long")

    def close_short(self, inst_id):
        """平掉指定SWAP合约的空头持仓"""
        positions = self.get_positions(inst_id)
        qty = positions.get("Sell", 0.0)
        if qty <= 0:
            print(f"[{datetime.now()}] 无空头持仓可平: {inst_id}")
            return None, False
        print(f"[{datetime.now()}] 平空仓 {inst_id} short {qty} 张")
        return self.swap_trade(inst_id=inst_id, side="buy", amount=qty, price=None, posSide="short")
    
    def set_leverage(self, instId, lever, mgnMode, posSide=None):
        """设置杠杆"""
        params = {
            "instId": instId,
            "lever": str(lever),
            "mgnMode": mgnMode,
        }
        if posSide:
            params["posSide"] = posSide
        return self.account_api.set_leverage(**params)

if __name__ == "__main__":
    client = OkxClient()
    print(client.get_ticker(['BTC-USDT-SWAP', 'DOGE-USDT-SWAP']))
    # print(client.get_positions('BTC-USDT-SWAP'))
    # client.close_short('DOGE-USDT-SWAP')
    # client.open_short('DOGE-USDT-SWAP', 0.1)
    # 下单示例
    # print(client.swap_trade(inst_id='DOGE-USDT-SWAP', side='sell', amount='0.1', price=None, posSide="short"))
    # print(client.swap_trade(inst_id='DOGE-USDT-SWAP', side='buy', amount='0.1', price=None, posSide="long"))
    # client.close_position('DOGE-USDT-SWAP')
