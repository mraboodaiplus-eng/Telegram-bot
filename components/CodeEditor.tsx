import React from 'react';
import { GeneratedScript } from '../types';

interface CodeEditorProps {
  script: GeneratedScript | null;
}

const CodeEditor: React.FC<CodeEditorProps> = ({ script }) => {
  if (!script) {
    return (
      <div className="h-full flex flex-col items-center justify-center bg-[#0c0c0e] border border-carbon-800 text-carbon-700">
        <svg className="w-12 h-12 mb-3 opacity-20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
           <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p className="font-mono text-[10px] uppercase tracking-widest opacity-40">Workspace Empty</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-[#0c0c0e] border border-carbon-800 shadow-panel overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-carbon-900 border-b border-carbon-800 shrink-0">
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-crimson-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
          </svg>
          <span className="text-xs font-mono text-carbon-100 font-bold tracking-wide">{script.filename}</span>
        </div>
        <div className="flex items-center gap-2">
             <span className="w-2 h-2 rounded-full bg-yellow-500/50"></span>
             <span className="text-[10px] text-carbon-400 font-mono uppercase">{script.language}</span>
        </div>
      </div>
      <div className="flex-1 p-3 overflow-auto font-mono text-xs md:text-sm bg-[#0c0c0e] text-carbon-100 leading-relaxed custom-scrollbar relative">
        <div className="absolute left-0 top-0 bottom-0 w-8 bg-carbon-900/30 border-r border-carbon-800/50 flex flex-col items-end pr-2 pt-3 text-[10px] text-carbon-700 select-none">
           {script.code.split('\n').map((_, i) => <div key={i}>{i+1}</div>)}
        </div>
        <pre className="pl-10 whitespace-pre-wrap selection:bg-crimson-900 selection:text-white outline-none">
          {script.code}
        </pre>
      </div>
    </div>
  );
};

export default CodeEditor;