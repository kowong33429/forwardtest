"use client";
import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';

export default function HistoryPage() {
  const params = useParams();
  const id = params.id;
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const [portfolio, setPortfolio] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [showThaiTime, setShowThaiTime] = useState(false);

  useEffect(() => {
    if (!id) return;
    
    const fetchHistory = async () => {
      try {
        const portRes = await fetch(`${API_URL}/portfolios`);
        const allPorts = await portRes.json();
        const currentPort = allPorts.find((p: any) => p.id === Number(id));
        
        if (currentPort) {
          const trRes = await fetch(`${API_URL}/trades/${id}`);
          const trades = await trRes.json();
          setPortfolio({ ...currentPort, trades });
        }
      } catch (e) {
        console.error("Error fetching history:", e);
      } finally {
        setLoading(false);
      }
    };
    
    fetchHistory();
  }, [id, API_URL]);

  const toggleRow = (tradeId: string) => {
    setExpandedRows(prev => ({ ...prev, [tradeId]: !prev[tradeId] }));
  };

  const formatTime = (isoString: string) => {
    const d = new Date(isoString);
    if (showThaiTime) {
      return d.toLocaleString('en-US', { timeZone: 'Asia/Bangkok' }) + ' (ICT)';
    } else {
      return d.toLocaleString('en-US', { timeZone: 'America/New_York' }) + ' (EST)';
    }
  };

  if (loading) return <div className="container" style={{textAlign: 'center', marginTop: '50px'}}>Loading History...</div>;
  if (!portfolio) return <div className="container" style={{textAlign: 'center', marginTop: '50px'}}>Portfolio not found.</div>;

  return (
    <div className="container">
      <div style={{marginBottom: '2rem'}}>
        <Link href="/" style={{color: 'var(--accent)', textDecoration: 'none', fontWeight: 'bold'}}>
          ← Back to Dashboard
        </Link>
      </div>

      <div className="card">
        <h2 style={{borderBottom: 'none', paddingBottom: 0}}>
          {portfolio.algorithm_name} - Trading History
        </h2>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: '2rem' }}>
          Detailed record of all trades and Gemini AI logic analysis.
        </p>

        {portfolio.trades && portfolio.trades.length > 0 ? (
          <table className="exchange-table expandable-table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Price</th>
                <th>Amount</th>
                <th>Total (USDT)</th>
                <th onClick={() => setShowThaiTime(!showThaiTime)} style={{cursor: 'pointer', textDecoration: 'underline dotted'}}>
                  Datetime ⏱️
                </th>
                <th>Stop Loss</th>
                <th>Max Risk</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.trades.map((trade: any) => {
                const isExpanded = !!expandedRows[`${trade.id}`];
                const reasonData = trade.reason ? (() => { try { return JSON.parse(trade.reason); } catch(e) { return null; } })() : null;
                const totalUsdt = trade.amount * trade.price;
                const actionColor = trade.action === 'BUY' ? 'var(--success)' : 'var(--danger)';

                return (
                  <React.Fragment key={trade.id}>
                    <tr onClick={() => toggleRow(`${trade.id}`)} className="clickable-row">
                      <td style={{color: actionColor, fontWeight: 'bold'}}>{trade.action}</td>
                      <td>${trade.price.toFixed(4)}</td>
                      <td>{trade.amount.toFixed(4)} {trade.symbol}</td>
                      <td>${totalUsdt.toFixed(2)}</td>
                      <td>{formatTime(trade.timestamp)}</td>
                      <td>{reasonData?.stop_loss_price ? `$${reasonData.stop_loss_price.toFixed(4)}` : '-'}</td>
                      <td style={{color: 'var(--danger)'}}>{reasonData?.est_loss_usd ? `-$${reasonData.est_loss_usd.toFixed(2)}` : '-'}</td>
                    </tr>
                    {isExpanded && (
                      <tr className="expanded-row">
                        <td colSpan={7} style={{padding: '1.5rem', background: 'rgba(0,0,0,0.2)'}}>
                          
                          {/* AI Insights Section */}
                          {trade.insight && (
                            <div className="mb-6 p-4 sm:p-5 rounded-xl bg-gradient-to-r from-indigo-900/40 to-purple-900/40 border border-indigo-500/30 shadow-lg shadow-indigo-500/10 backdrop-blur-md">
                              <div className="flex items-center gap-2 mb-4 border-b border-indigo-500/20 pb-3">
                                <span className="text-2xl">✨</span>
                                <h4 className="m-0 text-xl font-bold bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">Gemini AI Analysis</h4>
                              </div>
                              
                              <div className="space-y-4">
                                <div className="bg-black/20 rounded-lg p-4 border border-white/5">
                                  <div className="flex items-center gap-2 text-indigo-300 font-semibold mb-2">
                                    <span>📊</span> <span>Trade Summary</span>
                                  </div>
                                  <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap m-0">{trade.insight.summary}</p>
                                </div>

                                <div className="bg-black/20 rounded-lg p-4 border border-white/5">
                                  <div className="flex items-center gap-2 text-purple-300 font-semibold mb-2">
                                    <span>🌍</span> <span>Macro Context</span>
                                  </div>
                                  <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap m-0">{trade.insight.macro_context}</p>
                                </div>

                                <div className="bg-black/20 rounded-lg p-4 border border-white/5">
                                  <div className="flex items-center gap-2 text-pink-300 font-semibold mb-2">
                                    <span>💡</span> <span>Lessons Learned</span>
                                  </div>
                                  <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap m-0">{trade.insight.lessons_learned}</p>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Deep Decision Logic */}
                          {reasonData ? (
                            <div className="bg-black/30 p-4 sm:p-6 rounded-lg border-l-4 border-[var(--accent)]">
                              <h4 className="m-0 mb-4 text-[var(--accent)] text-base font-bold">🎯 Detailed Decision Logic</h4>
                              
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {Object.entries(reasonData).map(([key, value]: [string, any]) => {
                                  if (typeof value === 'object') return null; // skip nested arrays/objects
                                  return (
                                    <div key={key} className="text-sm">
                                      <strong className="text-purple-300 capitalize">{key.replace(/_/g, ' ')}:</strong> 
                                      <span className="ml-2 text-white">{value as React.ReactNode}</span>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          ) : (
                            <div style={{color: 'var(--text-muted)'}}>No deep decision logic available.</div>
                          )}

                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p style={{color: 'var(--text-muted)', fontStyle: 'italic', textAlign: 'center', padding: '2rem'}}>No trades yet for this algorithm.</p>
        )}
      </div>
    </div>
  );
}
