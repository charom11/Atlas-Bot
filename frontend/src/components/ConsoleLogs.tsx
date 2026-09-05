import React, { useEffect, useRef } from 'react';
import { Terminal } from 'lucide-react';

interface ConsoleLogsProps {
  logs: string;
}

export const ConsoleLogs: React.FC<ConsoleLogsProps> = ({ logs }) => {
  const consoleRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <section className="panel full-width-panel">
      <div className="panel-header">
        <h2>
          <Terminal size={18} />
          Live Engine Output & Signal Ledger
        </h2>
        <span className="sub-text">Real-time scan logs from weather_ensemble_bot.py</span>
      </div>
      <div className="console-box" ref={consoleRef}>
        <pre>{logs || 'Connecting to live bot engine...'}</pre>
      </div>
    </section>
  );
};
