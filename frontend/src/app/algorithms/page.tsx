"use client";
import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import LoadingSpinner from '../../components/LoadingSpinner';

export default function AlgorithmsDashboard() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  
  const [portfolios, setPortfolios] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPortfolios = async () => {
    try {
      const res = await fetch(`${API_URL}/portfolios`);
      const data = await res.json();
      setPortfolios(data);
    } catch (e) {
      console.error("Error fetching portfolios:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolios();
  }, []);

  const handleToggleHide = async (id: number) => {
    try {
      await fetch(`${API_URL}/portfolios/${id}/toggle_hide`, { method: 'POST' });
      fetchPortfolios();
    } catch (e) {
      alert("Error toggling hide");
    }
  };

  const handleToggleAI = async (id: number) => {
    try {
      await fetch(`${API_URL}/portfolios/${id}/toggle_ai`, { method: 'POST' });
      fetchPortfolios();
    } catch (e) {
      alert("Error toggling AI");
    }
  };

  const handleDelete = async (id: number) => {
    if (confirm("Are you sure you want to delete this algorithm? It will stop trading completely.")) {
      try {
        await fetch(`${API_URL}/portfolios/${id}`, { method: 'DELETE' });
        fetchPortfolios();
      } catch (e) {
        alert("Error deleting");
      }
    }
  };

  if (loading) return <LoadingSpinner text="Loading Algorithms..." />;

  return (
    <div className="container">
      <div className="header" style={{ marginBottom: '2rem' }}>
        <Link href="/" passHref>
          <button className="btn" style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)', marginBottom: '1rem' }}>
            ← Back to Dashboard
          </button>
        </Link>
        <h1>⚙️ Algorithms Management</h1>
        <p>Manage your running AI algorithms and portfolios.</p>
      </div>

      <div className="card overflow-x-auto">
        <table className="exchange-table min-w-full">
          <thead>
            <tr>
              <th>Algorithm Name</th>
              <th>Current Balance</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {portfolios.length === 0 ? (
              <tr>
                <td colSpan={3} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No algorithms found.</td>
              </tr>
            ) : (
              portfolios.map(port => {
                const pnl = port.balance_usd - 10000.0;
                const pnlSign = pnl >= 0 ? '+' : '';
                const pnlColor = pnl >= 0 ? 'var(--success)' : 'var(--danger)';

                return (
                  <tr key={port.id}>
                    <td style={{ fontWeight: 'bold' }}>
                      {port.algorithm_name}
                      <br/>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 'normal' }}>
                        File: {port.file_name || 'Unknown'} | AI: {port.is_ai_enabled ? '✅ Enabled' : '❌ Disabled'} | View: {port.is_hidden ? '🙈 Hidden' : '👁️ Visible'}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>
                        ${port.balance_usd.toFixed(2)}
                      </span>
                      <br/>
                      <span style={{ color: pnlColor, fontSize: '0.9rem' }}>
                        ({pnlSign}${pnl.toFixed(2)} from 10k)
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <button 
                          onClick={() => handleToggleHide(port.id)}
                          style={{
                            padding: '0.5rem 1rem', borderRadius: '4px', border: '1px solid var(--border)',
                            background: 'var(--surface)', color: 'var(--text)', cursor: 'pointer'
                          }}
                        >
                          {port.is_hidden ? 'Show Frontend' : 'Hide Frontend'}
                        </button>
                        <button 
                          onClick={() => handleToggleAI(port.id)}
                          style={{
                            padding: '0.5rem 1rem', borderRadius: '4px', border: '1px solid var(--border)',
                            background: 'var(--surface)', color: 'var(--text)', cursor: 'pointer'
                          }}
                        >
                          {port.is_ai_enabled ? 'Disable AI' : 'Enable AI'}
                        </button>
                        <button 
                          onClick={() => handleDelete(port.id)}
                          style={{
                            padding: '0.5rem 1rem', borderRadius: '4px', border: 'none',
                            background: 'var(--danger)', color: 'white', cursor: 'pointer'
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
