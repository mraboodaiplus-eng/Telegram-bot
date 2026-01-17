import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface ChatMessageComponentProps {
  content: string;
  role: 'user' | 'model' | 'system';
}

const ChatMessageComponent: React.FC<ChatMessageComponentProps> = ({ content, role }) => {
  const handleCopy = (code: string) => {
    navigator.clipboard.writeText(code);
  };

  return (
    <div className="markdown-body w-full overflow-hidden font-mono text-gray-200">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Headers: Big, Bold, Uppercase, NO GLOW. Using theme color for impact.
          h1: ({node, ...props}) => <h1 className="text-3xl font-display font-black border-b border-nebula-border pb-2 mb-4 mt-6 uppercase tracking-widest text-nebula-crimson" {...props} />,
          h2: ({node, ...props}) => <h2 className="text-2xl font-display font-bold mb-3 mt-5 uppercase tracking-wide text-nebula-crimson" {...props} />,
          h3: ({node, ...props}) => <h3 className="text-xl font-bold mb-2 mt-4 text-nebula-neon" {...props} />,
          
          // Bold text: High contrast white with colored underline instead of glow
          strong: ({node, ...props}) => <strong className="font-black text-white decoration-2 underline decoration-nebula-crimson underline-offset-4" {...props} />,
          
          // Lists
          ul: ({node, ...props}) => <ul className="list-disc pl-5 my-2 space-y-1 marker:text-nebula-crimson" {...props} />,
          ol: ({node, ...props}) => <ol className="list-decimal pl-5 my-2 space-y-1 marker:text-nebula-crimson" {...props} />,
          
          // Code handling
          code({ node, inline, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || '');
            const codeString = String(children).replace(/\n$/, '');
            
            // SyntaxHighlighter does not accept a ref that is meant for an HTMLElement
            // We extract it here to prevent the "No overload matches this call" error.
            const { ref, ...rest } = props;
            
            return !inline && match ? (
              // Block Code: Crisp, dark background, professional border
              <div className="relative group my-4 rounded-sm border border-nebula-border overflow-hidden shadow-lg bg-[#050101]">
                <div className="flex justify-between items-center bg-[#150a0a] px-3 py-1 border-b border-nebula-border">
                  <span className="text-xs text-nebula-crimson font-mono uppercase font-bold flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-nebula-crimson animate-pulse"></span>
                    {match[1]}
                  </span>
                  <button 
                    onClick={() => handleCopy(codeString)}
                    className="text-[10px] text-gray-400 hover:text-white uppercase tracking-widest border border-transparent hover:border-gray-600 px-2 rounded-sm transition-all flex items-center gap-1"
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                    COPY
                  </button>
                </div>
                <SyntaxHighlighter
                  {...rest}
                  style={vscDarkPlus}
                  language={match[1]}
                  PreTag="div"
                  customStyle={{
                    margin: 0,
                    padding: '1rem',
                    background: '#050101',
                    fontSize: '0.85rem',
                    lineHeight: '1.5',
                    textShadow: 'none', // Explicitly remove any syntax highlighter shadow
                  }}
                >
                  {codeString}
                </SyntaxHighlighter>
              </div>
            ) : (
              // Inline Code: No glow, high contrast background
              <code className={`${className} bg-white/10 text-nebula-neon px-1.5 py-0.5 rounded font-bold border border-white/5 font-mono text-sm`} {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="overflow-x-auto my-4 border border-nebula-border rounded-sm">
                <table className="w-full text-left border-collapse">{children}</table>
              </div>
            );
          },
          thead({ children }) {
            return <thead className="bg-white/5 text-nebula-crimson uppercase text-xs tracking-wider">{children}</thead>;
          },
          th({ children }) {
             return <th className="p-2 border-b border-nebula-border font-bold">{children}</th>
          },
          td({ children }) {
             return <td className="p-2 border-b border-white/5 text-sm font-mono">{children}</td>
          },
          blockquote({ children }) {
            return <blockquote className="border-l-2 border-nebula-dim pl-4 italic text-gray-500 my-2">{children}</blockquote>
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

export default ChatMessageComponent;