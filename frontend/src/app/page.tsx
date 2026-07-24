"use client";
import React, { useEffect, useState } from 'react';
import Link from 'next/link';

const DEMO_PORTFOLIOS = [
  {
    id: 991,
    algorithm_name: "V4.0 Aggressive",
    balance_usd: 10000.0,
    positions: [
      { id: 1, symbol: "BTCUSDT", amount: 0.1500, avg_entry_price: 64000.0 },
      { id: 2, symbol: "ETHUSDT", amount: 2.5000, avg_entry_price: 3400.0 }
    ],
    trades: [
      {
        id: 1,
        symbol: "SOLUSDT",
        action: "SELL",
        amount: 20.0,
        price: 145.5,
        profit_pct: 7.77,
        timestamp: new Date().toISOString(),
        insight: {
          summary: "SOL experienced a strong breakout following network upgrade news. Taking partial profits.",
          macro_context: "Broader crypto market is bullish. Fed rate pause provided tailwinds.",
          lessons_learned: "Holding winners longer works in trending markets, but taking 7% profit is a safe play."
        }
      }
    ]
  },
  {
    id: 992,
    algorithm_name: "V5.1 God Mode",
    balance_usd: 10000.0,
    positions: [
      { id: 3, symbol: "SOLUSDT", amount: 50.0000, avg_entry_price: 135.0 }
    ],
    trades: [
      {
        id: 2,
        symbol: "BTCUSDT",
        action: "BUY",
        amount: 0.05,
        price: 65000.0,
        profit_pct: null,
        timestamp: new Date().toISOString(),
        insight: null
      }
    ]
  }
];

export default function Home() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const [portfolios, setPortfolios] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [prices, setPrices] = useState<any[]>([]);
  const [viewMode, setViewMode] = useState<"live" | "demo">("live");
  
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [showThaiTime, setShowThaiTime] = useState(false);

  const toggleRow = (id: string) => {
    setExpandedRows(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const formatTime = (isoString: string) => {
    const d = new Date(isoString);
    if (showThaiTime) {
      return d.toLocaleString('en-US', { timeZone: 'Asia/Bangkok' }) + ' (ICT)';
    } else {
      return d.toLocaleString('en-US', { timeZone: 'America/New_York' }) + ' (EST)';
    }
  };

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
    const portInterval = setInterval(fetchPortfolios, 5000);
    const priceInterval = setInterval(fetchPrices, 3000);
    return () => {
      clearInterval(portInterval);
      clearInterval(priceInterval);
    };
  }, []);

  const handleForceTick = async () => {
    if (viewMode === "demo") {
      alert("Please switch to Live mode to trigger a real engine tick.");
      return;
    }
    try {
      await fetch(`${API_URL}/engine/tick`, { method: 'POST' });
      alert("Engine Tick Triggered!");
      setTimeout(fetchPortfolios, 2000);
    } catch (e) {
      alert("Failed to trigger tick");
    }
  };

  const displayPortfolios = viewMode === "demo" ? DEMO_PORTFOLIOS : portfolios;

  const calculateTotalValue = (port: any) => {
    let total = port.balance_usd;
    if (port.positions) {
      port.positions.forEach((pos: any) => {
        const livePrice = prices.find(p => p.symbol === pos.symbol)?.price || pos.avg_entry_price;
        total += pos.amount * livePrice;
      });
    }
    return total;
  };

  const groupPositions = (positions: any[]) => {
    if (!positions) return [];
    const grouped: Record<string, any> = {};
    positions.forEach(pos => {
      if (!grouped[pos.symbol]) {
        grouped[pos.symbol] = { ...pos };
      } else {
        const totalAmount = grouped[pos.symbol].amount + pos.amount;
        const avgPrice = ((grouped[pos.symbol].amount * grouped[pos.symbol].avg_entry_price) + (pos.amount * pos.avg_entry_price)) / totalAmount;
        grouped[pos.symbol].amount = totalAmount;
        grouped[pos.symbol].avg_entry_price = avgPrice;
      }
    });
    return Object.values(grouped);
  };

  if (loading) return <div className="container" style={{textAlign: 'center', marginTop: '50px'}}>Loading Dashboard...</div>;

  return (
    <>
      <div className="ticker-wrap">
        <div className="ticker" style={{ animationDuration: prices.length > 0 ? '20s' : '0s' }}>
          {prices.length > 0 ? (
            prices.map((p, i) => (
              <div className="ticker-item" key={i}>
                {p.symbol}: ${p.price.toFixed(4)} 
                <span style={{ color: p.change >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                  {p.change >= 0 ? '+' : ''}{p.change.toFixed(2)}%
                </span>
              </div>
            ))
          ) : (
            <div className="ticker-item" style={{ color: 'var(--text-muted)' }}>
              ⚠️ Cannot connect to Backend API. Live market data unavailable. Please check backend server.
            </div>
          )}
        </div>
      </div>
      
      <div className="container">
        <div className="header">
          <h1>🚀 AI Quant Live Paper Trading</h1>
          <p>Forward testing platform powered by Gemini AI</p>
          
          {/* Mode Switcher */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', margin: '2rem 0' }}>
            <button 
              onClick={() => setViewMode("live")}
              style={{
                padding: '0.5rem 2rem', 
                borderRadius: '20px', 
                border: viewMode === "live" ? '2px solid var(--success)' : '1px solid var(--border)',
                background: viewMode === "live" ? 'rgba(16, 185, 129, 0.2)' : 'transparent',
                color: viewMode === "live" ? 'var(--success)' : 'var(--text-muted)',
                cursor: 'pointer',
                fontWeight: 'bold',
                transition: 'all 0.3s ease'
              }}
            >
              🔴 Live Trades
            </button>
            <button 
              onClick={() => setViewMode("demo")}
              style={{
                padding: '0.5rem 2rem', 
                borderRadius: '20px', 
                border: viewMode === "demo" ? '2px solid var(--accent)' : '1px solid var(--border)',
                background: viewMode === "demo" ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
                color: viewMode === "demo" ? 'var(--accent)' : 'var(--text-muted)',
                cursor: 'pointer',
                fontWeight: 'bold',
                transition: 'all 0.3s ease'
              }}
            >
              ✨ Demo View
            </button>
          </div>

          <div className="btn-group">
            <button className="btn" onClick={handleForceTick} style={{ opacity: viewMode === "demo" ? 0.5 : 1 }}>
              Force Engine Tick (Simulate 4H)
            </button>
          </div>
        </div>

        <div className="dashboard-grid grid grid-cols-1 xl:grid-cols-2 gap-8">
          {displayPortfolios.length === 0 ? (
            <div style={{gridColumn: '1 / -1', textAlign: 'center', color: 'var(--text-muted)'}}>
              <h3>No portfolios found.</h3>
              <p>Trigger an Engine Tick to start trading.</p>
            </div>
          ) : (
            displayPortfolios.map(port => (
              <div className="card" key={port.id}>
                <h2>{port.algorithm_name}</h2>
                {port.description && (
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: '1rem', fontStyle: 'italic' }}>
                    {port.description}
                  </p>
                )}
                
                <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '0.5rem' }}>
                  Total Value
                </div>
                <div className="balance" style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>
                  ${calculateTotalValue(port).toFixed(2)}
                </div>
                <div style={{ color: 'var(--success)', fontWeight: 'bold', fontSize: '1.1rem' }}>
                  Cash Balance: ${port.balance_usd.toFixed(2)}
                </div>
                
                <h3 style={{color: 'var(--text-muted)', fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '1px', marginTop: '2rem'}}>Current Positions</h3>
                {port.positions && port.positions.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="exchange-table min-w-full">
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Avg Price</th>
                          <th>Initial Cost</th>
                          <th>Current Value</th>
                          <th>PnL</th>
                        </tr>
                      </thead>
                      <tbody>
                        {groupPositions(port.positions).map((pos: any) => {
                          const livePrice = prices.find(p => p.symbol === pos.symbol)?.price || pos.avg_entry_price;
                          const initialCost = pos.amount * pos.avg_entry_price;
                          const currentValue = pos.amount * livePrice;
                          const pnlUsd = currentValue - initialCost;
                          const pnlPct = (pnlUsd / initialCost) * 100;
                          const pnlColor = pnlUsd >= 0 ? 'var(--success)' : 'var(--danger)';
                          const pnlSign = pnlUsd >= 0 ? '+' : '';

                          return (
                            <tr key={pos.symbol}>
                              <td style={{fontWeight: '600'}}>{pos.symbol}</td>
                              <td>${pos.avg_entry_price.toFixed(4)}</td>
                              <td>${initialCost.toFixed(2)} USDT</td>
                              <td>${currentValue.toFixed(2)} USDT</td>
                              <td style={{color: pnlColor, fontWeight: 'bold'}}>
                                {pnlSign}{pnlUsd.toFixed(2)} USDT ({pnlSign}{pnlPct.toFixed(2)}%)
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p style={{color: 'var(--text-muted)', fontStyle: 'italic'}}>Holding 100% USDT (No active positions)</p>
                )}
                <div style={{marginTop: '2rem', display: 'flex', flexDirection: 'column', gap: '1rem'}}>
                  <Link href={`/history/${port.id}`} passHref>
                    <button className="btn" style={{width: '100%', background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', padding: '1rem'}}>
                      View Full Trading History & AI Insights ➔
                    </button>
                  </Link>
                  <Link href={`/ai-reports/${port.id}`} passHref>
                    <button className="btn" style={{width: '100%', background: 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%)', padding: '1rem'}}>
                      View AI Strategy Reports (Daily Optimizer) ➔
                    </button>
                  </Link>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
}
