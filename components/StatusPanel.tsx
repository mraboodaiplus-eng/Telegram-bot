import React from 'react';
import { AgentStatus } from '../types';

interface StatusPanelProps {
  status: AgentStatus;
}

const StatusPanel: React.FC<StatusPanelProps> = ({ status }) => {
  const getStatusColor = (s: AgentStatus) => {
    switch (s) {
      case AgentStatus.IDLE: return 'bg-nebula-dim';
      case AgentStatus.THINKING: return 'bg-purple-600';
      case AgentStatus.WRITING: return 'bg-nebula-warning';
      case AgentStatus.EXECUTING: return 'bg-nebula-primary'; // RED
      case AgentStatus.ANALYZING: return 'bg-blue-600';
      case AgentStatus.CORRECTING: return 'bg-orange-600';
      default: return 'bg-nebula-dim';
    }
  };

  const getStatusText = (s: AgentStatus) => {
    switch (s) {
      case AgentStatus.IDLE: return 'SYSTEM_IDLE';
      case AgentStatus.THINKING: return 'NEURAL_ANALYSIS';
      case AgentStatus.WRITING: return 'GENERATING_CODE';
      case AgentStatus.EXECUTING: return 'EXECUTING_ROOT';
      case AgentStatus.ANALYZING: return 'VERIFYING_OUTPUT';
      case AgentStatus.CORRECTING: return 'RECALIBRATING';
      default: return 'UNKNOWN';
    }
  };

  return (
    <div className="flex items-center gap-0 border border-nebula-primary/50 bg-nebula-bg/80 backdrop-blur-sm">
      <div className={`px-3 py-1 text-[10px] font-bold tracking-widest text-black ${getStatusColor(status)} animate-pulse`}>
        {status === AgentStatus.IDLE ? 'STBY' : 'ACTV'}
      </div>
      <div className="px-3 py-1 text-[10px] font-mono font-bold text-nebula-primary tracking-widest uppercase">
        STATUS: {getStatusText(status)}
      </div>
    </div>
  );
};

export default StatusPanel;