
import { GeneratedScript, Attachment } from "../types";

export class GeminiService {
  private backendUrl: string = window.location.origin; // Default to local, update for Render URL

  async generateResponse(
    prompt: string, 
    history: any[], 
    systemInstructionText: string,
    systemFile: Attachment | undefined,
    attachments: Attachment[] = [],
    customApiKey?: string
  ): Promise<string> {
    try {
      // --- NEBULA UPLINK ---
      // This sends the command to the Node.js/Puppeteer backend
      // which types it into the specific AI Studio session.
      
      const response = await fetch(`${this.backendUrl}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: prompt,
        })
      });

      if (!response.ok) {
        // Fallback for UI demonstration if backend is not running locally
        if (response.status === 404 || response.status === 500 || !response) {
           throw new Error("SERVER_UNREACHABLE");
        }
        const errorData = await response.json();
        throw new Error(errorData.error || "UPLINK_ERROR");
      }

      const data = await response.json();
      return data.response || "";

    } catch (error: any) {
      console.warn("NEBULA_BACKEND_OFFLINE: ", error);
      
      // --- MOCK FALLBACK (FOR UI PREVIEW) ---
      // This ensures the UI is usable even without the complex backend running
      if (error.message === "Failed to fetch" || error.message === "SERVER_UNREACHABLE") {
        return `[SYSTEM WARNING]: Backend Link Offline.
        
To activate the Satellite Uplink (Puppeteer Automation), you must deploy the provided 'server.js' and 'Dockerfile' to a platform like Render.com.

Current Status: SIMULATION_MODE
Target: Google AI Studio Session (19-FE9TkNS7CpJAmLStYEYOc7SdqlVPhC)
        
User Input Received: "${prompt}"`;
      }
      
      throw new Error(error.message || "NEURAL_UPLINK_FAILED");
    }
  }

  extractCode(response: string): GeneratedScript | null {
    // Priority 1: Bash commands (Terminal execution)
    const bashRegex = /```bash\n([\s\S]*?)```/;
    const bashMatch = response.match(bashRegex);

    if (bashMatch) {
       return {
         language: 'bash',
         code: bashMatch[1].trim(),
         filename: 'terminal_io',
         status: 'draft'
       };
    }

    // Priority 2: Full Scripts (Artifact Workspace)
    const codeBlockRegex = /```(python|javascript|js|html|c|cpp|go|rust|yaml|json|sh)\n([\s\S]*?)```/;
    const codeMatch = response.match(codeBlockRegex);
    
    if (codeMatch) {
      const language = codeMatch[1];
      const code = codeMatch[2].trim();
      let filename = 'artifact_output';
      if (language.includes('python')) filename = 'payload.py';
      if (language.includes('js')) filename = 'exploit.js';
      if (language.includes('html')) filename = 'report.html';
      if (language.includes('c')) filename = 'kernel_poc.c';

      return { language, code, filename, status: 'draft' };
    }
    return null;
  }
}

export const geminiService = new GeminiService();
