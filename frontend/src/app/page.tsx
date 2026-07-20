"use client";
import { useEffect, useState } from 'react';

export default function Home() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const [portfolios, setPortfolios] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [prices, setPrices] = useState<any[]>([]);

  const fetchPortfolios = async () => {
    try {
      const res = await fetch(`${API_URL}/portfolios`);
      const data = await res.json();
      
      const portsWithTrades = await Promise.all(data.map(async (p: any) => {
        const trRes = await fetch(`${API_URL}/trades/${p.id}`);
        const trades = await trRes.json();
        return { ...p, trades };
      }));
      
      setPortfolios(portsWithTrades);
    } catch (e) {
      console.error("Error fetching portfolios:", e);
    } finally {
      setLoading(false);
    }
  };

  const fetchPrices = async () => {
    try {
      const res = await fetch(`${API_URL}/market/prices`);
      const data = await res.json();
      if (data.status === "success") {
        setPrices(data.data);
      }
    } catch (e) {
      console.error("Error fetching prices:", e);
    }
  };

  useEffect(() => {
    fetchPortfolios();
    fetchPrices();
    const portInterval = setInterval(fetchPortfolios, 30000);
    const priceInterval = setInterval(fetchPrices, 10000);
    return () => {
      clearInterval(portInterval);
      clearInterval(priceInterval);
    };
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

  const handleLoadDemo = async () => {
    try {
      await fetch(`${API_URL}/engine/seed_test_data`, { method: 'POST' });
      alert("Demo Data Loaded Successfully!");
      setTimeout(fetchPortfolios, 1000);
    } catch (e) {
      alert("Failed to load demo data");
    }
  };

  if (loading) return <div className="container" style={{textAlign: 'center', marginTop: '50px'}}>Loading Dashboard...</div>;

  return (
    <>
      {prices.length > 0 && (
        <div className="ticker-wrap">
          <div className="ticker">
            {prices.map((p, i) => (
              <div className="ticker-item" key={i}>
                {p.symbol}: ${p.price.toFixed(4)} 
                <span style={{ color: p.change >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                  {p.change >= 0 ? '+' : ''}{p.change.toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      
      <div className="container">
        <div className="header">
          <h1>🚀 AI Quant Live Paper Trading</h1>
          <p>Forward testing platform powered by Gemini AI</p>
          <div className="btn-group">
            <button className="btn" onClick={handleForceTick}>
              Force Engine Tick (Simulate 4H)
            </button>
            <button className="btn demo" onClick={handleLoadDemo}>
              ✨ Load Demo Data
            </button>
          </div>
        </div>

        <div className="dashboard-grid">
          {portfolios.map(port => (
            <div className="card" key={port.id}>
              <h2>{port.algorithm_name}</h2>
              <div className="balance">${port.balance_usd.toFixed(2)}</div>
              
              <h3 style={{color: 'var(--text-muted)', fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '1px'}}>Current Positions</h3>
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
                        <td style={{fontWeight: '600'}}>{pos.symbol}</td>
                        <td>{pos.amount.toFixed(4)}</td>
                        <td>${pos.avg_entry_price.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p style={{color: 'var(--text-muted)', fontStyle: 'italic'}}>Holding 100% USDT (No active positions)</p>
              )}

              <h3 style={{marginTop: '2rem', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '0.5rem', color: 'var(--text-muted)', fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '1px'}}>
                Recent Trades & AI Insights
              </h3>
              <div style={{maxHeight: '400px', overflowY: 'auto', paddingRight: '0.5rem', marginTop: '1rem'}}>
                {port.trades && port.trades.length > 0 ? (
                  port.trades.map((trade: any) => (
                    <div key={trade.id} style={{marginBottom: '1.5rem', paddingBottom: '1rem', borderBottom: '1px solid rgba(255,255,255,0.05)'}}>
                      <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', alignItems: 'center'}}>
                        <span className={`badge ${trade.action.toLowerCase()}`}>{trade.action} {trade.symbol}</span>
                        <span style={{color: 'var(--text-muted)', fontSize: '0.8rem'}}>
                          {new Date(trade.timestamp).toLocaleString()}
                        </span>
                      </div>
                      <div style={{fontSize: '0.95rem'}}>
                        Amount: {trade.amount.toFixed(4)} @ ${trade.price.toFixed(4)}
                        {trade.profit_pct !== null && (
                          <span style={{marginLeft: '1rem', fontWeight: 'bold', color: trade.profit_pct >= 0 ? 'var(--success)' : 'var(--danger)'}}>
                            Profit: {trade.profit_pct > 0 ? '+' : ''}{trade.profit_pct.toFixed(2)}%
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
                  <p style={{color: 'var(--text-muted)', fontStyle: 'italic'}}>No trades yet.</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
