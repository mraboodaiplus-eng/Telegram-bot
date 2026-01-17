export enum MessageRole {
  USER = 'user',
  MODEL = 'model',
  SYSTEM = 'system'
}

export enum LogLevel {
  INFO = 'INFO',
  WARN = 'WARN',
  ERROR = 'ERROR',
  SUCCESS = 'SUCCESS',
  DEBUG = 'DEBUG',
  SYSTEM = 'SYSTEM'
}

export interface TerminalLog {
  id: string;
  timestamp: string;
  level: LogLevel;
  message: string;
}

export interface Attachment {
  mimeType: string;
  data: string; // Base64
  name: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  attachments?: Attachment[];
}

export interface GeneratedScript {
  language: string;
  code: string;
  filename: string;
  status: 'draft' | 'running' | 'completed' | 'failed';
}

export interface Session {
  id: string;
  title: string;
  messages: ChatMessage[];
  lastModified: number;
}

export enum AgentStatus {
  IDLE = 'IDLE',
  THINKING = 'ANALYZING',
  WRITING = 'GENERATING',
  EXECUTING = 'EXECUTING',
  ANALYZING = 'VERIFYING',
  CORRECTING = 'RECALIBRATING'
}

export interface AppSettings {
  systemPrompt: string;
  systemFile?: Attachment;
  autoExecute: boolean;
  autoHeal: boolean; 
  customApiKey?: string;
  themeColor?: string;
  // Visual Settings
  wallpaperMode: 'grid' | 'skull' | 'plain';
  enableCrtEffect: boolean;
}
