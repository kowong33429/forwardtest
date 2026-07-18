"use client";
import { useEffect, useState } from 'react';

export default function Home() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const [portfolios, setPortfolios] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPortfolios = async () => {
    try {
      const res = await fetch(`${API_URL}/portfolios`);
      const data = await res.json();
      
      // For each portfolio, fetch its trades
      const portsWithTrades = await Promise.all(data.map(async (p: any) => {
        const trRes = await fetch(`${API_URL}/trades/${p.id}`);
        const trades = await trRes.json();
        return { ...p, trades };
      }));
      
      setPortfolios(portsWithTrades);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolios();
    const interval = setInterval(fetchPortfolios, 30000); // Poll every 30s
    return () => clearInterval(interval);
  }, []);

  const handleForceTick = async () => {
    try {
      await fetch(`${API_URL}/engine/tick`, { method: 'POST' });
      alert("Engine Tick Triggered!");
      setTimeout(fetchPortfolios, 2000);
    } catch (e) {
      alert("Failed to trigger tick");
    }
  };

  if (loading) return <div className="container">Loading Dashboard...</div>;

  return (
    <div className="container">
      <div className="header">
        <h1>🚀 AI Quant Live Paper Trading</h1>
        <p>Forward testing platform powered by Gemini AI</p>
        <button className="btn" style={{marginTop: '1rem'}} onClick={handleForceTick}>
          Force Engine Tick (Simulate 4H)
        </button>
      </div>

      <div className="dashboard-grid">
        {portfolios.map(port => (
          <div className="card" key={port.id}>
            <h2>{port.algorithm_name}</h2>
            <div className="balance">${port.balance_usd.toFixed(2)}</div>
            
            <h3>Current Positions</h3>
            {port.positions && port.positions.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    <th>Coin</th>
                    <th>Amount</th>
                    <th>Avg Price</th>
                  </tr>
                </thead>
                <tbody>
                  {port.positions.map((pos: any) => (
                    <tr key={pos.id}>
                      <td>{pos.symbol}</td>
                      <td>{pos.amount.toFixed(4)}</td>
                      <td>${pos.avg_entry_price.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p style={{color: 'var(--text-muted)'}}>Holding 100% USDT (No active positions)</p>
            )}

            <h3 style={{marginTop: '2rem', borderBottom: '1px solid var(--border)', paddingBottom: '0.5rem'}}>
              Recent Trades & AI Insights
            </h3>
            <div style={{maxHeight: '400px', overflowY: 'auto'}}>
              {port.trades && port.trades.length > 0 ? (
                port.trades.map((trade: any) => (
                  <div key={trade.id} style={{marginBottom: '1.5rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border)'}}>
                    <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem'}}>
                      <span className={`badge ${trade.action.toLowerCase()}`}>{trade.action} {trade.symbol}</span>
                      <span style={{color: 'var(--text-muted)', fontSize: '0.9rem'}}>
                        {new Date(trade.timestamp).toLocaleString()}
                      </span>
                    </div>
                    <div>
                      Amount: {trade.amount.toFixed(4)} @ ${trade.price.toFixed(4)}
                      {trade.profit_pct !== null && (
                        <span style={{marginLeft: '1rem', color: trade.profit_pct >= 0 ? 'var(--success)' : 'var(--danger)'}}>
                          Profit: {trade.profit_pct.toFixed(2)}%
                        </span>
                      )}
                    </div>
                    
                    {trade.insight && (
                      <div className="ai-insight">
                        <h4>🧠 Gemini Analysis</h4>
                        <p><strong>Summary:</strong> {trade.insight.summary}</p>
                        <p><strong>Macro:</strong> {trade.insight.macro_context}</p>
                        <p><strong>Lesson:</strong> {trade.insight.lessons_learned}</p>
                      </div>
                    )}
                  </div>
                ))
              ) : (
                <p style={{color: 'var(--text-muted)'}}>No trades yet.</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
