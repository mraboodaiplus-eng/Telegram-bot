
import React, { useState, useEffect, useRef } from 'react';
import Terminal from './components/Terminal';
import CodeEditor from './components/CodeEditor';
import StatusPanel from './components/StatusPanel';
import ChatMessageComponent from './components/ChatMessageComponent';
import { geminiService } from './services/geminiService';
import { ChatMessage, MessageRole, TerminalLog, LogLevel, GeneratedScript, AgentStatus, AppSettings, Attachment, Session } from './types';

// Helper to safely encode Unicode strings to Base64
const utf8_to_b64 = (str: string) => {
  return window.btoa(unescape(encodeURIComponent(str)));
};

// --- ENHANCED 3D SKULL ---
const HolographicSkull = () => {
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  
  useEffect(() => {
    const handleMove = (e: MouseEvent) => {
      // Gentle parallax effect
      setMousePos({ 
        x: (e.clientX / window.innerWidth - 0.5) * 15, 
        y: (e.clientY / window.innerHeight - 0.5) * 15 
      });
    };
    window.addEventListener('mousemove', handleMove);
    return () => window.removeEventListener('mousemove', handleMove);
  }, []);

  return (
    <div className="fixed inset-0 z-0 flex items-center justify-center pointer-events-none perspective-container overflow-hidden">
      {/* Moving Grid Floor */}
      <div className="cyber-grid"></div>
      
      {/* 3D Skull Container */}
      <div 
        className="relative w-[600px] h-[600px] transition-transform duration-200 ease-out opacity-80"
        style={{ transform: `rotateY(${mousePos.x}deg) rotateX(${-mousePos.y}deg)` }}
      >
         {/* Layer 1: The Glow Behind */}
         <div className="absolute inset-0 flex items-center justify-center blur-[80px] opacity-40">
            <div className="w-64 h-64 bg-nebula-crimson rounded-full animate-pulse"></div>
         </div>

         {/* Layer 2: Rotating Outer Rings */}
         <div className="absolute inset-0 flex items-center justify-center">
             <div className="w-[500px] h-[500px] border border-nebula-crimson/20 rounded-full animate-spin-slow border-dashed"></div>
         </div>
         <div className="absolute inset-0 flex items-center justify-center">
             <div className="w-[400px] h-[400px] border border-nebula-neon/10 rounded-full animate-spin-reverse-slow border-dotted"></div>
         </div>

         {/* Layer 3: The Skull SVG (Main) */}
         <div className="absolute inset-0 flex items-center justify-center animate-float" style={{ transform: 'translateZ(50px)' }}>
            <svg viewBox="0 0 24 24" className="w-[320px] h-[320px] text-nebula-crimson drop-shadow-[0_0_15px_rgba(var(--primary-color),0.8)]" fill="none" stroke="currentColor" strokeWidth="0.8">
               {/* Simplified but aggressive Skull Path */}
               <path d="M12 2C7 2 4 6 4 11C4 16 6 19 8 20C8 21 9 22 12 22C15 22 16 21 16 20C18 19 20 16 20 11C20 6 17 2 12 2Z" fill="rgba(0,0,0,0.5)" />
               <path d="M8 12C8 12.5 8.5 13 9 13C9.5 13 10 12.5 10 12C10 11.5 9.5 11 9 11C8.5 11 8 11.5 8 12Z" fill="currentColor" />
               <path d="M14 12C14 12.5 14.5 13 15 13C15.5 13 16 12.5 16 12C16 11.5 15.5 11 15 11C14.5 11 14 11.5 14 12Z" fill="currentColor" />
               <path d="M10 17C10.5 16 11 15.5 12 15.5C13 15.5 13.5 16 14 17" strokeLinecap="round" />
               <path d="M12 15.5V17.5" />
               {/* Cyber Accents */}
               <path d="M2 11H5" strokeOpacity="0.5" />
               <path d="M19 11H22" strokeOpacity="0.5" />
               <circle cx="12" cy="5" r="1" fill="currentColor" className="animate-ping" />
            </svg>
         </div>

         {/* Layer 4: Front HUD Elements */}
         <div className="absolute inset-0 flex items-center justify-center" style={{ transform: 'translateZ(100px)' }}>
             <svg className="w-[350px] h-[350px] text-nebula-neon opacity-30 animate-spin-slow" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="48" stroke="currentColor" strokeWidth="0.5" fill="none" strokeDasharray="10 5" />
                <path d="M50 2V10 M50 90V98 M2 50H10 M90 50H98" stroke="currentColor" strokeWidth="1" />
             </svg>
         </div>
      </div>
    </div>
  );
};

export const App: React.FC = () => {
  // --- STATE ---
  const [sessions, setSessions] = useState<Session[]>(() => {
    const saved = localStorage.getItem('nebula_sessions_v2');
    return saved ? JSON.parse(saved) : [{ id: 'default', title: 'Start Mission', messages: [], lastModified: Date.now() }];
  });
  const [activeSessionId, setActiveSessionId] = useState<string>(() => {
    return localStorage.getItem('nebula_active_session') || 'default';
  });
  const [showSidebar, setShowSidebar] = useState(window.innerWidth > 1024);
  
  const [input, setInput] = useState('');
  const [terminalLogs, setTerminalLogs] = useState<TerminalLog[]>([]);
  const [currentArtifact, setCurrentArtifact] = useState<GeneratedScript | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentStatus>(AgentStatus.IDLE);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [activeTab, setActiveTab] = useState<'COMM' | 'OPS'>('COMM');
  
  const [showSettings, setShowSettings] = useState(false);
  
  // NOTE: System Prompt logic removed as state is now managed by the AI Studio Session backend.
  const [settings, setSettings] = useState<AppSettings>(() => {
    const saved = localStorage.getItem('nebula_settings_v3');
    const defaultSettings = { 
      systemPrompt: "", // Controlled by AI Studio
      autoExecute: true, 
      autoHeal: true,
      themeColor: '#ff003c',
      wallpaperMode: 'skull',
      enableCrtEffect: true
    };
    
    if (saved) return JSON.parse(saved);
    return defaultSettings as AppSettings;
  });
  
  const [secondaryColor, setSecondaryColor] = useState('#00f3ff');

  const activeSession = sessions.find(s => s.id === activeSessionId) || sessions[0];
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    localStorage.setItem('nebula_sessions_v2', JSON.stringify(sessions));
    localStorage.setItem('nebula_active_session', activeSessionId);
  }, [sessions, activeSessionId]);

  useEffect(() => {
    localStorage.setItem('nebula_settings_v3', JSON.stringify(settings));
    if (settings.themeColor) {
      document.documentElement.style.setProperty('--primary-color', settings.themeColor);
    }
    document.documentElement.style.setProperty('--secondary-color', secondaryColor);
  }, [settings, secondaryColor]);

  useEffect(() => {
    if (chatContainerRef.current) chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
  }, [activeSession.messages, activeTab]);

  const createNewSession = () => {
    const newSession: Session = {
      id: Math.random().toString(36).substr(2, 9),
      title: `OP-${Math.floor(Math.random()*1000)}`,
      messages: [],
      lastModified: Date.now()
    };
    setSessions([newSession, ...sessions]);
    setActiveSessionId(newSession.id);
    if (window.innerWidth < 1024) setShowSidebar(false);
  };

  const deleteSession = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (sessions.length <= 1) return;
    const filtered = sessions.filter(s => s.id !== id);
    setSessions(filtered);
    if (activeSessionId === id) setActiveSessionId(filtered[0].id);
  };

  const updateActiveSessionMessages = (msgs: ChatMessage[]) => {
    setSessions(prev => prev.map(s => s.id === activeSessionId ? { ...s, messages: msgs, lastModified: Date.now() } : s));
  };

  const addLog = (level: LogLevel, message: string) => {
    const time = new Date().toLocaleTimeString('en-US', { hour12: false });
    setTerminalLogs(prev => [...prev, { id: Math.random().toString(), timestamp: time, level, message }]);
  };

  const simulateCommandExecution = async (command: string) => {
    setAgentStatus(AgentStatus.EXECUTING);
    addLog(LogLevel.SYSTEM, `root@nebula:~$ ${command}`);
    await new Promise(r => setTimeout(r, 1500));
    
    let output = "Command execution successful.";
    let isError = false;

    if (command.includes('scan') || command.includes('nmap')) {
      output = `Target 192.168.1.X is active.\nPorts: 80 (HTTP), 22 (SSH).\nOS: Linux Kernel 5.10.`;
    } else if (command.includes('fail')) {
      isError = true;
      output = "Connection timed out (Error 504).";
    }

    addLog(isError ? LogLevel.ERROR : LogLevel.SUCCESS, output);
    
    const obs: ChatMessage = {
      id: Math.random().toString(),
      role: MessageRole.SYSTEM,
      content: `[TERMINAL_OUTPUT]\nCMD: ${command}\nRESULT: ${output}`,
      timestamp: new Date()
    };
    updateActiveSessionMessages([...activeSession.messages, obs]);
    setAgentStatus(AgentStatus.IDLE);
  };

  const handleSendMessage = async () => {
    if (!input.trim() && attachments.length === 0) return;
    const currentAttachments = [...attachments];
    const prompt = input;
    setInput('');
    setAttachments([]);

    const userMsg: ChatMessage = { id: Math.random().toString(), role: MessageRole.USER, content: prompt, timestamp: new Date(), attachments: currentAttachments };
    const newMsgs = [...activeSession.messages, userMsg];
    updateActiveSessionMessages(newMsgs);
    setAgentStatus(AgentStatus.THINKING);

    try {
      // Use empty history/system prompt as the session state is held by the AI Studio URL on the backend
      const response = await geminiService.generateResponse(
          prompt, 
          [], 
          "", 
          undefined, 
          currentAttachments, 
          undefined
      );
      
      const modelMsg: ChatMessage = { id: Math.random().toString(), role: MessageRole.MODEL, content: response, timestamp: new Date() };
      
      updateActiveSessionMessages([...newMsgs, modelMsg]);

      const extracted = geminiService.extractCode(response);
      if (extracted) {
        if (extracted.language === 'bash' && settings.autoExecute) simulateCommandExecution(extracted.code);
        else if (extracted.language !== 'bash') {
          setCurrentArtifact(extracted);
          if (window.innerWidth < 1024) setActiveTab('OPS');
        }
      }
      setAgentStatus(AgentStatus.IDLE);
    } catch (e: any) {
      updateActiveSessionMessages([...newMsgs, { id: Math.random().toString(), role: MessageRole.SYSTEM, content: `ERROR: ${e.message}`, timestamp: new Date() }]);
      setAgentStatus(AgentStatus.IDLE);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) {
      const file = e.target.files[0];
      const reader = new FileReader();
      reader.onload = () => {
        const att = { name: file.name, mimeType: file.type || 'text/plain', data: (reader.result as string).split(',')[1] };
        setAttachments(p => [...p, att]);
      };
      reader.readAsDataURL(file);
    }
  };

  return (
    <div className="flex h-[100dvh] w-full text-white overflow-hidden font-display relative selection:bg-nebula-crimson selection:text-black">
      {/* --- VISUAL EFFECTS LAYER --- */}
      <HolographicSkull />
      <div className="scanlines"></div>
      <div className="vignette"></div>
      
      {/* --- CONTENT LAYER (Z-INDEX 50) --- */}
      <div className="relative z-50 flex w-full h-full p-2 md:p-6 gap-6 perspective-container">
        
        {/* --- LEFT SIDEBAR (HOLOGRAPHIC) --- */}
        <aside className={`
            holo-panel flex flex-col transition-all duration-300
            ${showSidebar ? 'w-72 translate-x-0' : 'w-0 -translate-x-full opacity-0 pointer-events-none absolute'}
            shrink-0
        `}>
          {/* Header */}
          <div className="p-4 border-b border-nebula-border bg-black/40 flex items-center justify-between">
             <div>
               <h1 className="text-2xl font-cyber font-bold text-nebula-crimson screen-glitch">NEBULA</h1>
               <div className="text-[10px] text-nebula-neon font-mono tracking-widest mt-1">
                  UPLINK: SATELLITE_CORE
               </div>
             </div>
             <button onClick={() => setShowSidebar(false)} className="md:hidden text-nebula-crimson hover:text-white">✕</button>
          </div>
          
          {/* Action Button */}
          <div className="p-4">
             <button 
                onClick={createNewSession}
                className="w-full py-3 bg-nebula-crimson/10 border border-nebula-crimson hover:bg-nebula-crimson hover:text-black transition-all text-nebula-crimson font-bold tracking-widest text-xs uppercase clip-hex relative overflow-hidden group"
             >
               <span className="relative z-10 flex items-center justify-center gap-2">
                 <span className="text-lg leading-none">+</span> CLEAR CONSOLE
               </span>
               <div className="absolute inset-0 bg-nebula-crimson transform translate-y-full group-hover:translate-y-0 transition-transform duration-300"></div>
             </button>
          </div>

          {/* Session List */}
          <div className="flex-1 overflow-y-auto custom-scrollbar p-3 space-y-1">
             <div className="flex items-center gap-2 px-2 mb-2 opacity-50">
                <div className="w-1.5 h-1.5 bg-nebula-crimson rounded-full animate-pulse"></div>
                <span className="text-[10px] font-mono font-bold tracking-[0.2em] text-nebula-crimson uppercase">Operations History</span>
             </div>
             {sessions.map(s => (
                <div key={s.id} onClick={() => { setActiveSessionId(s.id); if(window.innerWidth < 1024) setShowSidebar(false); }}
                  className={`
                    group p-3 border-l-2 cursor-pointer transition-all flex justify-between items-center bg-black/20 hover:bg-nebula-crimson/10
                    ${s.id === activeSessionId ? 'border-nebula-crimson text-white shadow-[inset_10px_0_20px_-10px_rgba(var(--primary-color),0.2)]' : 'border-transparent text-gray-500 hover:text-gray-300'}
                  `}
                >
                   <div className="flex flex-col">
                      <span className="font-mono text-xs font-bold tracking-wide">{s.title}</span>
                      <span className="text-[9px] opacity-50 font-mono">{s.id.toUpperCase()}</span>
                   </div>
                   <button onClick={(e) => deleteSession(s.id, e)} className="opacity-0 group-hover:opacity-100 text-nebula-crimson hover:text-white transition-all">✕</button>
                </div>
             ))}
          </div>

          {/* Config Button */}
          <div className="p-4 border-t border-nebula-border bg-black/40">
             <button onClick={() => setShowSettings(true)} className="w-full flex items-center justify-center gap-2 text-xs font-bold text-gray-400 hover:text-nebula-neon transition-colors tracking-widest uppercase">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"/></svg>
                System Config
             </button>
          </div>
        </aside>

        {/* --- MAIN COCKPIT --- */}
        <main className="flex-1 flex flex-col min-w-0 holo-panel overflow-hidden">
           {/* Top HUD */}
           <header className="h-16 flex items-center justify-between px-6 border-b border-nebula-border bg-black/40 relative">
              <div className="absolute top-0 left-0 w-20 h-[1px] bg-nebula-crimson"></div>
              <div className="absolute bottom-0 right-0 w-20 h-[1px] bg-nebula-crimson"></div>
              
              <div className="flex items-center gap-4">
                 <button onClick={() => setShowSidebar(!showSidebar)} className="text-gray-400 hover:text-nebula-crimson transition-colors">
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16"/></svg>
                 </button>
                 <StatusPanel status={agentStatus} />
              </div>

              <div className="hidden md:flex items-center gap-6 text-[10px] font-mono tracking-widest text-gray-500">
                 <div className="flex flex-col items-end">
                    <span className="text-nebula-crimson">PROTOCOL</span>
                    <span>PUPPETEER_V2</span>
                 </div>
                 <div className="w-[1px] h-6 bg-gray-800"></div>
                 <div className="flex flex-col items-end">
                    <span className="text-nebula-neon">TARGET</span>
                    <span>AI_STUDIO_SESSION_19</span>
                 </div>
              </div>
           </header>

           {/* Mobile Tabs */}
           <div className="lg:hidden flex border-b border-nebula-border bg-black/50">
              <button onClick={() => setActiveTab('COMM')} className={`flex-1 py-3 text-[10px] font-bold tracking-[0.2em] ${activeTab === 'COMM' ? 'text-nebula-crimson bg-white/5 border-b-2 border-nebula-crimson' : 'text-gray-500'}`}>COMM</button>
              <button onClick={() => setActiveTab('OPS')} className={`flex-1 py-3 text-[10px] font-bold tracking-[0.2em] ${activeTab === 'OPS' ? 'text-nebula-crimson bg-white/5 border-b-2 border-nebula-crimson' : 'text-gray-500'}`}>OPS</button>
           </div>

           <div className="flex-1 flex overflow-hidden relative">
              {/* CHAT AREA */}
              <div className={`${activeTab === 'COMM' ? 'flex' : 'hidden lg:flex'} flex-col w-full lg:w-[50%] h-full border-r border-nebula-border bg-black/60 relative z-10`}>
                 <div className="flex-1 overflow-y-auto p-5 space-y-8 custom-scrollbar" ref={chatContainerRef}>
                    {activeSession.messages.length === 0 && (
                       <div className="h-full flex flex-col items-center justify-center pointer-events-none select-none opacity-80">
                          <div className="relative">
                             <div className="absolute inset-0 bg-nebula-crimson blur-xl opacity-20 animate-pulse"></div>
                             <svg className="w-24 h-24 text-nebula-crimson animate-spin-slow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="0.5">
                                <circle cx="12" cy="12" r="10" strokeDasharray="4 4" />
                                <path d="M12 2v20M2 12h20" strokeOpacity="0.5" />
                             </svg>
                          </div>
                          <h2 className="mt-6 text-xl font-cyber tracking-[0.3em] text-white">NEBULA ONLINE</h2>
                          <p className="text-xs text-nebula-crimson font-mono mt-2">LINKED TO AI STUDIO SESSION</p>
                       </div>
                    )}
                    
                    {activeSession.messages.map(m => (
                       <div key={m.id} className={`flex flex-col ${m.role === MessageRole.USER ? 'items-end' : 'items-start'} animate-pulse-fast`}>
                          <div className={`
                             max-w-[90%] p-4 relative border
                             ${m.role === MessageRole.USER 
                               ? 'bg-zinc-900 border-zinc-700 rounded-bl-xl rounded-tr-xl text-right text-gray-300' 
                               : 'bg-black/80 border-nebula-neon/30 rounded-br-xl rounded-tl-xl text-left shadow-[0_0_15px_rgba(var(--primary-color),0.1)]'}
                          `}>
                             <div className={`text-[9px] font-black tracking-widest mb-2 flex items-center gap-2 ${m.role === MessageRole.USER ? 'justify-end text-gray-500' : 'text-nebula-neon'}`}>
                                {m.role === MessageRole.USER ? ':: OPERATOR' : ':: REMOTE_INTELLIGENCE'}
                                <span className="w-1 h-1 bg-current rounded-full"></span>
                             </div>
                             <ChatMessageComponent content={m.content} role={m.role} />
                          </div>
                       </div>
                    ))}
                    
                    {agentStatus === AgentStatus.THINKING && (
                       <div className="flex items-center gap-2 pl-4 text-nebula-neon font-mono text-xs animate-pulse">
                          <span>> REMOTE UPLINK ACTIVE... TRANSMITTING</span>
                          <span className="w-2 h-4 bg-nebula-neon animate-pulse"></span>
                       </div>
                    )}
                 </div>

                 {/* Input Area */}
                 <div className="p-4 bg-black/80 border-t border-nebula-border relative">
                    {/* Attachment Bar */}
                    {attachments.length > 0 && (
                       <div className="flex gap-2 mb-2 overflow-x-auto pb-2 custom-scrollbar">
                          {attachments.map((a, i) => (
                             <div key={i} className="flex items-center gap-2 px-3 py-1 bg-nebula-crimson/20 border border-nebula-crimson text-[10px] text-white font-mono uppercase">
                                <span className="truncate max-w-[100px]">{a.name}</span>
                                <button onClick={() => setAttachments(p => p.filter((_, idx) => idx !== i))} className="hover:text-red-500">×</button>
                             </div>
                          ))}
                       </div>
                    )}
                    
                    <div className="flex items-end gap-0 border border-nebula-dim bg-black p-1 focus-within:border-nebula-crimson focus-within:shadow-[0_0_15px_rgba(var(--primary-color),0.3)] transition-all">
                       <button onClick={() => fileInputRef.current?.click()} className="p-3 text-gray-500 hover:text-white hover:bg-white/5 transition-colors">
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" /></svg>
                          <input type="file" className="hidden" ref={fileInputRef} onChange={handleFileUpload} />
                       </button>
                       <textarea 
                          className="flex-1 bg-transparent border-none outline-none text-sm text-white font-mono placeholder-gray-600 min-h-[44px] max-h-32 py-3 px-2 resize-none"
                          placeholder="TRANSMIT COMMAND..."
                          value={input}
                          onChange={(e) => setInput(e.target.value)}
                          onKeyDown={(e) => { if(e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(); }}}
                       />
                       <button 
                          onClick={handleSendMessage} 
                          disabled={(!input.trim() && attachments.length === 0) || agentStatus !== AgentStatus.IDLE}
                          className="p-3 bg-nebula-crimson text-black font-bold hover:bg-white transition-all disabled:opacity-20 disabled:cursor-not-allowed"
                       >
                          <svg className="w-5 h-5 transform rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" /></svg>
                       </button>
                    </div>
                 </div>
              </div>

              {/* OPS AREA */}
              <div className={`${activeTab === 'OPS' ? 'flex' : 'hidden lg:flex'} flex-1 flex-col h-full bg-black/90 relative z-0 border-l border-nebula-border`}>
                 <div className="h-1/2 border-b border-nebula-border relative group">
                    <div className="absolute top-0 right-0 bg-nebula-neon/20 text-nebula-neon border-l border-b border-nebula-neon text-[9px] font-bold px-3 py-1 z-10 font-mono">ARTIFACT_VIEWER</div>
                    <CodeEditor script={currentArtifact} />
                 </div>
                 <div className="h-1/2 relative bg-black">
                    <div className="absolute top-0 right-0 bg-nebula-crimson/20 text-nebula-crimson border-l border-b border-nebula-crimson text-[9px] font-bold px-3 py-1 z-10 font-mono">ROOT_TERMINAL</div>
                    <Terminal logs={terminalLogs} isExecuting={agentStatus === AgentStatus.EXECUTING} />
                 </div>
              </div>
           </div>
        </main>

        {/* SETTINGS OVERLAY (HOLOGRAPHIC MODAL) */}
        {showSettings && (
           <div className="fixed inset-0 z-[100] bg-black/90 flex items-center justify-center p-4">
              <div className="holo-panel w-full max-w-2xl bg-black border border-nebula-crimson/50 shadow-[0_0_50px_rgba(var(--primary-color),0.2)]">
                 <div className="p-6 border-b border-nebula-border flex justify-between items-center bg-nebula-crimson/5">
                    <h2 className="font-cyber font-bold text-xl tracking-[0.2em] text-white">SYSTEM_CONFIG</h2>
                    <button onClick={() => setShowSettings(false)} className="text-gray-400 hover:text-white transition-colors">✕</button>
                 </div>
                 
                 <div className="p-8 space-y-8 overflow-y-auto max-h-[70vh] custom-scrollbar">
                    {/* COLOR CUSTOMIZATION */}
                    <div className="space-y-4 border-b border-white/10 pb-6">
                        <label className="text-[10px] font-bold text-white tracking-widest uppercase flex items-center gap-2">
                           <span className="w-2 h-2 bg-nebula-crimson rounded-full"></span>
                           UI Theme Customization
                        </label>
                        <div className="grid grid-cols-2 gap-6">
                            <div>
                                <label className="text-[9px] text-gray-400 block mb-2 uppercase">Primary Color (Crimson)</label>
                                <div className="flex items-center gap-2">
                                    <input 
                                        type="color" 
                                        value={settings.themeColor} 
                                        onChange={(e) => setSettings(s => ({...s, themeColor: e.target.value}))}
                                        className="w-12 h-10 bg-transparent border border-gray-600 p-0 cursor-pointer" 
                                    />
                                    <span className="font-mono text-xs text-nebula-crimson">{settings.themeColor}</span>
                                </div>
                            </div>
                            <div>
                                <label className="text-[9px] text-gray-400 block mb-2 uppercase">Secondary Color (Neon)</label>
                                <div className="flex items-center gap-2">
                                    <input 
                                        type="color" 
                                        value={secondaryColor} 
                                        onChange={(e) => setSecondaryColor(e.target.value)}
                                        className="w-12 h-10 bg-transparent border border-gray-600 p-0 cursor-pointer" 
                                    />
                                    <span className="font-mono text-xs text-nebula-neon">{secondaryColor}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-2">
                        <p className="text-xs text-gray-500">
                            NOTE: Authentication and System Prompts are now managed server-side via the Puppeteer backend connecting to Google AI Studio.
                        </p>
                    </div>

                 </div>

                 <div className="p-6 border-t border-nebula-border bg-black/80 flex justify-end">
                    <button onClick={() => setShowSettings(false)} className="px-10 py-3 bg-nebula-crimson text-black font-bold font-cyber tracking-widest hover:bg-white hover:scale-105 transition-all shadow-[0_0_20px_rgba(var(--primary-color),0.5)]">
                       CLOSE
                    </button>
                 </div>
              </div>
           </div>
        )}

      </div>
    </div>
  );
};
