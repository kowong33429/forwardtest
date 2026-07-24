"use client";
import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import LoadingSpinner from '../../../components/LoadingSpinner';

export default function AIReportsPage() {
  const params = useParams();
  const id = params.id;
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const [portfolio, setPortfolio] = useState<any>(null);
  const [reports, setReports] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    
    const fetchData = async () => {
      try {
        // Fetch portfolio info
        const portRes = await fetch(`${API_URL}/portfolios`);
        const allPorts = await portRes.json();
        const currentPort = allPorts.find((p: any) => p.id === Number(id));
        if (currentPort) {
          setPortfolio(currentPort);
        }

        // Fetch reports
        const optRes = await fetch(`${API_URL}/optimization/${id}`);
        if (optRes.ok) {
          const optData = await optRes.json();
          setReports(optData);
        }
      } catch (error) {
        console.error("Failed to fetch AI reports", error);
      } finally {
        setLoading(false);
      }
    };
    
    fetchData();
  }, [id, API_URL]);

  const formatTime = (isoString: string) => {
    return new Date(isoString).toLocaleString('th-TH');
  };

  if (loading) {
    return <LoadingSpinner text="Loading AI Reports..." />;
  }

  if (!portfolio) {
    return <div className="p-8 text-center text-white">Portfolio not found.</div>;
  }

  return (
    <div className="container min-h-screen text-white">
      <Link href="/" className="text-[var(--accent)] hover:underline mb-6 inline-block">
        ← Back to Dashboard
      </Link>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold m-0">🤖 AI Strategy Reports</h1>
          <p className="text-gray-400 mt-2">Daily Optimization insights for <strong className="text-white">{portfolio.algorithm_name}</strong></p>
        </div>
      </div>

      <div className="space-y-6">
        {reports.length === 0 ? (
          <div className="bg-black/30 p-8 rounded-xl text-center text-gray-400 border border-white/5">
            No daily optimization reports available yet for this portfolio.
          </div>
        ) : (
          reports.map((report) => (
            <div key={report.id} className="p-5 sm:p-6 rounded-xl bg-gradient-to-r from-teal-900/40 to-blue-900/40 border border-teal-500/30 shadow-lg shadow-teal-500/10 backdrop-blur-md">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6 border-b border-teal-500/20 pb-4">
                <div className="flex items-center gap-2">
                  <span className="text-2xl">🤖</span>
                  <div>
                    <h3 className="m-0 text-xl font-bold bg-gradient-to-r from-teal-400 to-blue-400 bg-clip-text text-transparent">
                      Daily Optimizer (AI 1.2)
                    </h3>
                    <span className="text-xs text-gray-400 block mt-1">{formatTime(report.timestamp)}</span>
                  </div>
                </div>
                
                <div className={`px-4 py-1.5 rounded-full text-sm font-bold border ${report.needs_tuning ? 'bg-orange-900/50 border-orange-500 text-orange-300' : 'bg-green-900/50 border-green-500 text-green-300'}`}>
                  Status: {report.needs_tuning ? 'Needs Tuning ⚠️' : 'Optimal ✅'}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-black/20 rounded-lg p-5 border border-white/5">
                  <div className="flex items-center gap-2 text-teal-300 font-semibold mb-3">
                    <span>📈</span> <span className="text-lg">Pattern Analysis</span>
                  </div>
                  <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap m-0">
                    {report.analysis}
                  </p>
                </div>

                <div className="bg-black/20 rounded-lg p-5 border border-white/5">
                  <div className="flex items-center gap-2 text-blue-300 font-semibold mb-3">
                    <span>🔧</span> <span className="text-lg">Suggested Parameters to Change</span>
                  </div>
                  <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap m-0">
                    {report.suggested_changes}
                  </p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
