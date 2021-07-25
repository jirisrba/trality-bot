#
# trality bot: SuperTrend Indicator
#
# Trality API: https://docs.trality.com/trality-code-editor/api-documentation
# Super Trend python library:
#   https://medium.datadriveninvestor.com/crypto-quant-profits-with-supertrend-indicator-f518129e1f5d
#
from enum import Enum

INTERVAL = "1h"

# supertrend calculation
PERIOD = 10
ATR_MULTIPLIER = 3

# max buy limit USDT
BUY_MAX_LIMIT = 50
STOP_LOSS = 0.1
TAKE_PROFIT = 0.5

SYMBOLS = [
    "AAVEUSDT",
    "ADAUSDT",
    "ATOMUSDT",
    "AUDIOUSDT",
    "ETHUSDT",
    "ICPUSDT",
    "LINKUSDT",
    "SOLUSDT",
    "THETAUSDT",
]


class Signal(Enum):
    IGNORE = 0
    BUY = 1
    SELL = 2


def initialize(state):
    state.signals = {}


def make_double_barrier(symbol, amount, take_profit, stop_loss, state):

    """make_double_barrier

    This function creates two iftouched market orders with the onecancelsother
    scope. It is used for our tripple-barrier-method

    Args:
        amount (float): units in base currency to sell
        take_profit (float): take-profit percent
        stop_loss (float): stop-loss percent
        state (state object): the state object of the handler function

    Returns:
        TralityOrder:  two order objects

    """

    with OrderScope.one_cancels_others():
        order_upper = order_take_profit(symbol, amount, take_profit, subtract_fees=True)
        order_lower = order_stop_loss(symbol, amount, stop_loss, subtract_fees=True)

    if order_upper.status != OrderStatus.Pending:
        errmsg = "make_double barrier failed with: {}"
        raise ValueError(errmsg.format(order_upper.error))

    # saving orders
    state["order_upper"] = order_upper
    state["order_lower"] = order_lower
    state["created_time"] = order_upper.created_time

    return order_upper, order_lower


def tr(data):
    """
    Calculate True Range
    indicator = data.tr()
    """
    data["previous_close"] = data["close"].shift(1)
    data["high-low"] = abs(data["high"] - data["low"])
    data["high-pc"] = abs(data["high"] - data["previous_close"])
    data["low-pc"] = abs(data["low"] - data["previous_close"])

    tr = data[["high-low", "high-pc", "low-pc"]].max(axis=1)

    return tr


def atr(data, period):
    """
    Calculate Average True Range
    indicator = data.atr(period=5)
    """
    data["tr"] = tr(data)
    atr = data["tr"].rolling(period).mean()

    return atr


def supertrend(df, period=PERIOD, atr_multiplier=ATR_MULTIPLIER):
    """Calculate Supertrend"""
    hl2 = (df["high"] + df["low"]) / 2
    df["atr"] = atr(df, period)
    df["upperband"] = hl2 + (atr_multiplier * df["atr"])
    df["lowerband"] = hl2 - (atr_multiplier * df["atr"])
    df["in_uptrend"] = True

    for current in range(1, len(df.index)):
        previous = current - 1

        if df["close"][current] > df["upperband"][previous]:
            df["in_uptrend"][current] = True
        elif df["close"][current] < df["lowerband"][previous]:
            df["in_uptrend"][current] = False
        else:
            df["in_uptrend"][current] = df["in_uptrend"][previous]

            if (
                df["in_uptrend"][current]
                and df["lowerband"][current] < df["lowerband"][previous]
            ):
                df["lowerband"][current] = df["lowerband"][previous]

            if not (
                df["in_uptrend"][current]
                and df["upperband"][current] > df["upperband"][previous]
            ):
                df["upperband"][current] = df["upperband"][previous]

    return df


def resolve_signal(data):
    """Compute a signal for a specific symbol pair"""

    df = supertrend(data.to_pandas())

    last_row_index = len(df.index) - 1
    previous_row_index = last_row_index - 1

    if not df["in_uptrend"][previous_row_index] and df["in_uptrend"][last_row_index]:
        print("changed to uptrend")
        return Signal.BUY

    if df["in_uptrend"][previous_row_index] and not df["in_uptrend"][last_row_index]:
        print("changed to downtrend")
        return Signal.SELL

    return Signal.IGNORE


@schedule(interval=INTERVAL, symbol=SYMBOLS, window_size=200)
def handler(state, data):
    """main()"""

    # Get portfolio and check information
    portfolio = query_portfolio()
    balance_quoted = portfolio.excess_liquidity_quoted
    print(balance_quoted)

    buy_value = min(float(balance_quoted) * 0.95, BUY_MAX_LIMIT)

    for symbol, symbol_data in data.items():

        # Resolve all signals
        action = resolve_signal(symbol_data)

        print("symbol: {} => action: {}".format(symbol, action))

        position = query_open_position_by_symbol(symbol, include_dust=False)
        has_position = position is not None

        # buy action
        if action == Signal.BUY and not has_position:
            print("Buy Signal: creating market order for {}".format(symbol))
            buy_order = order_market_value(symbol=symbol, value=buy_value)
            order_upper, order_lower = make_double_barrier(
                buy_order.symbol,
                float(buy_order.quantity),
                STOP_LOSS,
                TAKE_PROFIT,
                state,
            )
            print(
                "Buy value: {} at price: {} OCO order limit: {} stop {} ".format(
                    buy_value, symbol_data.close_last, order_upper, order_lower
                )
            )

        elif action == Signal.SELL and has_position:
            close_position(symbol)
            logmsg = "Sell Signal: closing {} position with exposure {} at current market price {}"
            print(
                logmsg.format(symbol, float(position.exposure), symbol_data.close_last)
            )
