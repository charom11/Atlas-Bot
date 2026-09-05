import type {
  PositionsResponse,
  EngineStatusResponse,
  MilestonesResponse,
  MTFHeatmapItem,
  PotatoSRResponse,
  DivergenceResponse,
  OrderFlowData,
} from '../types';

const API_BASE = '/api';

export async function fetchEngineStatus(): Promise<EngineStatusResponse> {
  const res = await fetch(`${API_BASE}/status`);
  return res.json();
}

export async function fetchPositions(): Promise<PositionsResponse> {
  const res = await fetch(`${API_BASE}/positions`);
  return res.json();
}

export async function fetchMilestones(): Promise<MilestonesResponse> {
  const res = await fetch(`${API_BASE}/milestones`);
  return res.json();
}

export async function fetchMTFHeatmap(): Promise<MTFHeatmapItem[]> {
  const res = await fetch(`${API_BASE}/mtf_heatmap`);
  const data = await res.json();
  return data.heatmap || [];
}

export async function fetchPotatoSR(symbol: string): Promise<PotatoSRResponse> {
  const res = await fetch(`${API_BASE}/potato_sr?symbol=${encodeURIComponent(symbol)}`);
  return res.json();
}

export async function fetchDivergence(symbol: string): Promise<DivergenceResponse> {
  const res = await fetch(`${API_BASE}/divergence?symbol=${encodeURIComponent(symbol)}`);
  return res.json();
}

export async function fetchOrderFlow(symbol: string): Promise<OrderFlowData> {
  const res = await fetch(`${API_BASE}/orderflow?symbol=${encodeURIComponent(symbol)}`);
  return res.json();
}

export async function fetchLogs(): Promise<string> {
  const res = await fetch(`${API_BASE}/logs`);
  const data = await res.json();
  return data.logs || '';
}

export async function startEngine(params: Record<string, any> = {}): Promise<any> {
  const res = await fetch(`${API_BASE}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function stopEngine(): Promise<any> {
  const res = await fetch(`${API_BASE}/stop`, {
    method: 'POST',
  });
  return res.json();
}

export async function closePosition(symbol: string): Promise<any> {
  const res = await fetch(`${API_BASE}/close_position`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol }),
  });
  return res.json();
}

export async function emergencyCloseAll(): Promise<any> {
  const res = await fetch(`${API_BASE}/close_all`, {
    method: 'POST',
  });
  return res.json();
}
