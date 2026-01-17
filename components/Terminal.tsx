import React, { useEffect, useRef } from 'react';
import { TerminalLog, LogLevel } from '../types';

interface TerminalProps {
  logs: TerminalLog[];
  isExecuting: boolean;
}

const Terminal: React.FC<TerminalProps> = ({ logs, isExecuting }) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll logic
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const getLogColor = (level: LogLevel) => {
    switch (level) {
      case LogLevel.INFO: return 'text-carbon-400';
      case LogLevel.WARN: return 'text-amber-500';
      case LogLevel.ERROR: return 'text-crimson-500 font-bold';
      case LogLevel.SUCCESS: return 'text-emerald-500';
      case LogLevel.DEBUG: return 'text-carbon-400 italic';
      case LogLevel.SYSTEM: return 'text-white font-bold border-b border-carbon-700 pb-0.5 mb-1 inline-block';
      default: return 'text-carbon-100';
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#0c0c0e] border border-carbon-800 font-mono text-sm relative overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-carbon-900 border-b border-carbon-800 select-none z-10 shrink-0">
        <div className="flex items-center gap-2">
           <svg className="w-3 h-3 text-crimson-600" viewBox="0 0 24 24" fill="currentColor"><path d="M4 6h18V4H4c-1.1 0-2 .9-2 2v11H0v3h14v-3H4V6zm19 2h-6c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V9c0-.55-.45-1-1-1zm-1 9h-4v-7h4v7z"/></svg>
           <span className="text-[10px] font-bold text-carbon-400 uppercase tracking-widest">/bin/bash - root</span>
        </div>
        <div className="flex gap-1.5 opacity-50">
          <div className="w-2 h-2 rounded-full bg-carbon-700"></div>
          <div className="w-2 h-2 rounded-full bg-carbon-700"></div>
        </div>
      </div>
      
      {/* Logs Container - CRITICAL FIX FOR MOBILE SCROLLING */}
      {/* min-h-0 is essential for nested flex containers to scroll properly */}
      <div 
        ref={scrollRef}
        className="flex-1 min-h-0 p-3 overflow-y-auto space-y-1 overscroll-contain touch-pan-y scroll-smooth z-0"
        style={{ WebkitOverflowScrolling: 'touch' }}
      >
        <div className="text-carbon-400 mb-3 text-xs opacity-50"># NEBULA SECURE SHELL SESSION STARTED</div>
        
        {logs.map((log) => (
          <div key={log.id} className="flex gap-3 text-xs md:text-sm font-medium leading-relaxed group hover:bg-white/5 p-0.5 -mx-1 px-1 rounded transition-colors">
            <span className="text-carbon-700 select-none w-[60px] shrink-0 text-[10px] pt-0.5 font-sans tabular-nums opacity-60">{log.timestamp}</span>
            <div className="flex-1 break-words">
                {log.level === LogLevel.SYSTEM ? (
                    <div className="text-white font-bold border-l-2 border-crimson-600 pl-2 py-1 bg-white/5 mb-1 mt-1">
                        {log.message}
                    </div>
                ) : (
                    <div className="flex gap-2">
                         <span className={`uppercase text-[10px] tracking-wider w-[40px] shrink-0 pt-0.5 ${getLogColor(log.level)}`}>{log.level}</span>
                         <span className="text-carbon-100">{log.message}</span>
                    </div>
                )}
            </div>
          </div>
        ))}
        
        {isExecuting && (
          <div className="mt-2 flex items-center gap-2 text-crimson-500 animate-pulse pl-1">
            <span className="text-xs font-bold">$</span>
            <span className="w-2 h-4 bg-crimson-500 block"></span>
          </div>
        )}
        
        {/* Spacer to ensure last item isn't hidden behind mobile bars */}
        <div className="h-10 md:h-2"></div> 
      </div>
    </div>
  );
};

export default Terminal;