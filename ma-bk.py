#
# trality bot: Brandon D Kelly: 7 - 77 - 231 Indicator
#

from enum import Enum

INTERVAL = "1h"

# max buy limit USDT
BUY_MAX_LIMIT = 100
STOP_LOSS = 0.1
TAKE_PROFIT = 0.5

SYMBOLS = [
    "AAVEUSDT",
    "ADAUSDT",
    "ATOMUSDT",
    "AUDIOUSDT",
    "BTCUSDT",
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
    state.number_offset_trades = 0


def resolve_signal(data):
    """Compute a signal for a specific symbol pair"""

    ma_short = data.sma(7).last
    ma_long = data.sma(77).last

    if ma_short > ma_long:
        return Signal.BUY

    elif ma_short < ma_long:
        return Signal.SELL

    # return Signal.IGNORE


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


@schedule(interval=INTERVAL, symbol=SYMBOLS)
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
