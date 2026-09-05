export interface BinancePosition {
  symbol: string;
  positionAmt: number;
  entryPrice: number;
  markPrice: number;
  unrealizedProfit: number;
  liquidationPrice: number;
  leverage: string | number;
  marginType: string;
  side: 'LONG' | 'SHORT';
}

export interface PositionsResponse {
  status: string;
  balance: number;
  total_unrealized_pnl: number;
  positions_count: number;
  positions: BinancePosition[];
  error?: string;
}

export interface EngineStatusResponse {
  running: boolean;
  pid: number | null;
}

export interface MilestonesResponse {
  status: string;
  current_balance: number;
  peak_balance: number;
  locked_milestone: number;
  next_milestone: number;
  progress_pct: number;
}

export interface MTFHeatmapItem {
  symbol: string;
  price: number;
  tf_5m: string;
  tf_15m: string;
  tf_1h: string;
  tf_4h: string;
  confluence: string;
  status: string;
}

export interface PotatoSRResponse {
  status: string;
  symbol?: string;
  current_price?: number;
  support?: number;
  resistance?: number;
  dist_to_sup_pct?: number;
  dist_to_res_pct?: number;
  state?: string;
  error?: string;
}

export interface DivergenceResponse {
  status: string;
  symbol?: string;
  rsi_14?: number;
  cci_20?: number;
  divergence_state?: string;
  confluence_grade?: string;
  bull_div?: boolean;
  bear_div?: boolean;
  macro_bull?: boolean;
  macro_bear?: boolean;
}

export interface OrderFlowData {
  status: string;
  data?: {
    symbol: string;
    net_delta: number;
    delta_pct: number;
    poc_price: number;
    dom_ratio: number;
    absorption: string;
    description: string;
  };
}

export interface LiveTrade {
  id: number;
  time: string;
  side: 'BUY' | 'SELL';
  price: number;
  qty: number;
  totalUsdt: number;
  isWhale: boolean;
}

export interface QuantModel {
  id: string;
  name: string;
  pillar: string;
  pillarNum: number;
  weight: number;
  score: number;
  signal: 'BUY' | 'SELL' | 'HOLD';
  description: string;
}
