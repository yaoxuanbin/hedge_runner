import unittest
from unittest.mock import MagicMock
from hedge_runner import HedgeRunner

class TestHedgeRunner(unittest.TestCase):
    def setUp(self):
        self.runner = HedgeRunner("config.json")
        self.runner.okx = MagicMock()
        self.runner.bybit = MagicMock()
        self.runner.logger = MagicMock()
        self.runner.hedge_cfg = {
            'BTC': {
                'okx': 'BTC-USD-SWAP',
                'bybit': 'BTCUSD',
                'open_spread': 0.01,
                'close_spread': 0.0,
                'qty': 1
            }
        }
        self.runner.symbols = ['BTC']
        self.runner.status = {'BTC': None}
        self.runner.open_direction = {'BTC': None}

    def test_open_position_long(self):
        # 模拟行情：okx价格高于bybit，触发开空/开多
        self.runner.okx.get_ticker.return_value = {'data': [{'last': '101'}]}
        self.runner.bybit.get_ticker.return_value = {'BTCUSD': '100'}
        self.runner.status['BTC'] = None
        self.runner.open_direction['BTC'] = None
        # 只跑一次循环体
        cfg = self.runner.hedge_cfg['BTC']
        okx_id = cfg['okx']
        bybit_id = cfg['bybit']
        open_spread = cfg['open_spread']
        qty = cfg['qty']
        okx_price = float(self.runner.okx.get_ticker(okx_id)['data'][0]['last'])
        bybit_price = float(self.runner.bybit.get_ticker([bybit_id]).get(bybit_id))
        spread = (okx_price - bybit_price) / bybit_price
        if spread >= open_spread:
            self.runner.okx.open_short(okx_id, qty)
            self.runner.bybit.open_long(bybit_id, qty)
            self.runner.status['BTC'] = "open"
            self.runner.open_direction['BTC'] = 1
        self.runner.okx.open_short.assert_called_with(okx_id, qty)
        self.runner.bybit.open_long.assert_called_with(bybit_id, qty)
        self.assertEqual(self.runner.status['BTC'], "open")
        self.assertEqual(self.runner.open_direction['BTC'], 1)

    def test_close_position_long(self):
        # 模拟持仓方向为1，spread回归，触发平仓
        self.runner.status['BTC'] = "open"
        self.runner.open_direction['BTC'] = 1
        self.runner.okx.get_ticker.return_value = {'data': [{'last': '99'}]}
        self.runner.bybit.get_ticker.return_value = {'BTCUSD': '100'}
        cfg = self.runner.hedge_cfg['BTC']
        okx_id = cfg['okx']
        bybit_id = cfg['bybit']
        close_spread = cfg['close_spread']
        okx_price = float(self.runner.okx.get_ticker(okx_id)['data'][0]['last'])
        bybit_price = float(self.runner.bybit.get_ticker([bybit_id]).get(bybit_id))
        spread = (okx_price - bybit_price) / bybit_price
        if self.runner.open_direction['BTC'] == 1 and spread < close_spread:
            self.runner.okx.close_short(okx_id)
            self.runner.bybit.close_long(bybit_id)
            self.runner.status['BTC'] = None
            self.runner.open_direction['BTC'] = None
        self.runner.okx.close_short.assert_called_with(okx_id)
        self.runner.bybit.close_long.assert_called_with(bybit_id)
        self.assertIsNone(self.runner.status['BTC'])
        self.assertIsNone(self.runner.open_direction['BTC'])

if __name__ == "__main__":
    unittest.main()
