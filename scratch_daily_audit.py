import os, sys, time, requests, hmac, hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

load_dotenv()
API_KEY = os.getenv('BINANCE_API_KEY', '')
API_SECRET = os.getenv('BINANCE_API_SECRET', '')

# Compute server time offset
server_offset = 0
try:
    r_time = requests.get('https://fapi.binance.com/fapi/v1/time', timeout=3).json()
    if 'serverTime' in r_time:
        server_offset = int(r_time['serverTime']) - int(time.time() * 1000)
except Exception:
    pass

def signed_req(method, path, params=None):
    if params is None: params = {}
    params['timestamp'] = int(time.time() * 1000) + server_offset
    params['recvWindow'] = 10000
    qs = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    sig = hmac.new(API_SECRET.encode('utf-8'), qs.encode('utf-8'), hashlib.sha256).hexdigest()
    try:
        res = requests.request(method, f"https://fapi.binance.com{path}?{qs}&signature={sig}", headers={'X-MBX-APIKEY': API_KEY}, timeout=5).json()
        return res
    except Exception as e:
        return {'error': str(e)}

acc = signed_req('GET', '/fapi/v2/account')
wb = float(acc.get('totalWalletBalance', 0)) if isinstance(acc, dict) else 0.0
mb = float(acc.get('totalMarginBalance', 0)) if isinstance(acc, dict) else 0.0
ab = float(acc.get('availableBalance', 0)) if isinstance(acc, dict) else 0.0
up = float(acc.get('totalUnrealizedProfit', 0)) if isinstance(acc, dict) else 0.0

# Use /fapi/v2/positionRisk for accurate markPrice, liquidationPrice, uPnL
position_risk = signed_req('GET', '/fapi/v2/positionRisk')
positions = [p for p in (position_risk if isinstance(position_risk, list) else []) if float(p.get('positionAmt', 0)) != 0]
open_orders = signed_req('GET', '/fapi/v1/openOrders')
algo_orders_raw = signed_req('GET', '/fapi/v1/openAlgoOrders')

now_ms = int(time.time() * 1000) + server_offset
income_raw = signed_req('GET', '/fapi/v1/income', {'startTime': now_ms - (24 * 3600 * 1000), 'limit': 100})
income_24h = income_raw if isinstance(income_raw, list) else []

print("=" * 80)
print("             BINANCE FUTURES LIVE ACCOUNT & RISK AUDIT")
print(f"             Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
print("=" * 80)
print(f"💰 WALLET OVERVIEW:")
print(f"   • Total Wallet Balance:     ${wb:,.4f} USDT")
print(f"   • Total Margin Balance:     ${mb:,.4f} USDT")
print(f"   • Available Free Margin:    ${ab:,.4f} USDT")
print(f"   • Unrealized Profit (uPnL): ${up:+,.4f} USDT")
print(f"   • Margin Utilization:       {((wb - ab) / wb * 100) if wb > 0 else 0.0:.2f}%")
print("-" * 80)

print(f"📈 ACTIVE OPEN POSITIONS ({len(positions)}):")
if not positions:
    print("   ✨ Zero open positions. (100% free margin ready for next setup)")
else:
    for p in positions:
        amt = float(p.get('positionAmt', 0))
        side = "LONG 🟢" if amt > 0 else "SHORT 🔴"
        ep = float(p.get('entryPrice', 0))
        mp = float(p.get('markPrice', 0))
        liq = float(p.get('liquidationPrice', 0))
        upnl = float(p.get('unRealizedProfit', 0))
        lev = p.get('leverage')
        notional = abs(float(p.get('notional', 0)))
        print(f"   • {p['symbol']} {side} ({lev}x): Qty={abs(amt)} | Entry=${ep:,.4f} | Mark=${mp:,.4f} | Liq=${liq:,.4f} | uPnL=${upnl:+,.4f} USDT")
        if liq > 0 and mp > 0:
            dist = abs(mp - liq) / mp * 100
            print(f"     └─ Notional=${notional:,.2f} | Distance to Liq: {dist:.2f}%")
print("-" * 80)

print(f"📋 ORDER BOOK STATUS:")
open_orders_list = open_orders if isinstance(open_orders, list) else []
if isinstance(algo_orders_raw, dict):
    algo_orders_list = algo_orders_raw.get('orders', [])
elif isinstance(algo_orders_raw, list):
    algo_orders_list = algo_orders_raw
else:
    algo_orders_list = []
print(f"   • Open Limit Orders:        {len(open_orders_list)}")
print(f"   • Open Algo Orders (SL/TP): {len(algo_orders_list)}")
if not open_orders_list and not algo_orders_list:
    print("   ✨ Clean order book. Zero orphaned orders.")
else:
    for o in open_orders_list:
        print(f"     - Limit: #{o.get('orderId')} {o.get('symbol')} {o.get('side')} {o.get('origQty')} @ ${float(o.get('price',0)):,.4f}")
    for a in algo_orders_list:
        trigger = float(a.get('stopPrice') or a.get('activationPrice') or a.get('triggerPrice') or 0)
        print(f"     - Algo: #{a.get('algoId')} {a.get('symbol')} {a.get('side','')} {a.get('orderType','')} trigger=${trigger:,.4f}")
print("-" * 80)

realized_24h = [r for r in income_24h if isinstance(r, dict) and r.get('incomeType') == 'REALIZED_PNL']
comm_24h = sum(float(r.get('income', 0)) for r in income_24h if isinstance(r, dict) and r.get('incomeType') == 'COMMISSION')
funding_24h = sum(float(r.get('income', 0)) for r in income_24h if isinstance(r, dict) and r.get('incomeType') == 'FUNDING_FEE')
net_realized_24h = sum(float(r.get('income', 0)) for r in realized_24h)

print(f"📊 24-HOUR REALIZED INCOME & TRADES:")
print(f"   • Realized Trade PnL:       ${net_realized_24h:+,.4f} USDT ({len(realized_24h)} trade fills)")
print(f"   • Trading Commissions:      ${comm_24h:+,.4f} USDT")
print(f"   • Net Funding Fees:         ${funding_24h:+,.4f} USDT")
print(f"   • Total Net Cash Flow:      ${(net_realized_24h + comm_24h + funding_24h):+,.4f} USDT")

if realized_24h:
    print(f"\n   Recent Trade Settlements:")
    for r in sorted(realized_24h, key=lambda x: x.get('time', 0), reverse=True)[:6]:
        t_str = datetime.fromtimestamp(int(r.get('time', 0)) / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        pnl = float(r.get('income', 0))
        sym = r.get('symbol', 'UNKNOWN')
        icon = "🟢" if pnl > 0 else "🔴"
        print(f"     {icon} {t_str} | {sym:<10} | Realized PnL: ${pnl:+,.4f} USDT")
print("=" * 80)
