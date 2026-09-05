import React from 'react';
import { Award } from 'lucide-react';
import type { MilestonesResponse } from '../types';

interface MilestoneBannerProps {
  milestones: MilestonesResponse | null;
}

export const MilestoneBanner: React.FC<MilestoneBannerProps> = ({ milestones }) => {
  if (!milestones) return null;

  const current = milestones.current_balance || 0;
  const floor = milestones.locked_milestone || 0;
  const nextTarget = milestones.next_milestone || 30;
  const pct = Math.min(100, Math.max(0, milestones.progress_pct || 0));

  return (
    <div className="milestone-banner">
      <div className="milestone-info">
        <span className="milestone-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Award size={16} /> ACCOUNT MILESTONE LOCK
        </span>
        <span className="milestone-details">
          Wallet: <strong>${current.toFixed(2)} USDT</strong> | Milestone Floor:{' '}
          <strong>${floor.toFixed(2)} USDT</strong> | Next Target:{' '}
          <strong>${nextTarget.toFixed(2)} USDT</strong> ({pct.toFixed(1)}%)
        </span>
      </div>
      <div className="milestone-progress-bar">
        <div className="milestone-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
};
