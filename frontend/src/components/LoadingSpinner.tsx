import React from 'react';

export default function LoadingSpinner({ text = "Loading..." }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-6">
      <div className="relative flex justify-center items-center h-24 w-24">
        <div className="absolute inset-0 border-t-4 border-blue-500 rounded-full animate-spin opacity-80"></div>
        <div className="absolute inset-2 border-r-4 border-purple-500 rounded-full animate-[spin_1.5s_reverse_infinite] opacity-80"></div>
        <div className="absolute inset-4 border-b-4 border-teal-400 rounded-full animate-spin opacity-80"></div>
        <span className="text-3xl animate-pulse absolute">🤖</span>
      </div>
      <h2 className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 font-bold text-xl animate-pulse tracking-widest uppercase">
        {text}
      </h2>
    </div>
  );
}
