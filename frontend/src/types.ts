export type Role = 'admin' | 'manager' | 'user';
export type View = 'rag-workbench' | 'overview' | 'chat' | 'knowledge' | 'tasks' | 'models' | 'observability' | 'settings' | 'applications' | 'collaboration' | 'requirements' | 'contracts' | 'exceptions';
export interface KnowledgeBase { id: string; name: string; description: string; category: string; color: string; tags: string[]; embedding: string; embeddingConfigId?:string; updatedAt: string; status: 'ready' | 'indexing' | 'empty'; }
export interface Chunk { id: string; title: string; content: string; location: string; kind: 'text' | 'table' | 'image'; edited?: boolean; assetUrl?:string; metadata?:Record<string,unknown>; parentId?: string; role?: 'parent' | 'child' | 'leaf'; parentExcerpt?: string; parentContext?: string; splitter?: string; }
export interface DocMetadata {
  docDate?: string | null;
  bizVersion?: string | null;
  subject?: string | null;
  ownerPerson?: string | null;
  keywords?: string[];
  likelyQuestions?: string[];
  extractedAt?: string;
  extractor?: { mode?: string; modelConfigId?: string; edited?: boolean; llmAttempted?: boolean };
  confidence?: number | null;
  status?: string;
}
export interface KnowledgeDoc { id: string; kbId: string; name: string; kind: string; size: string; chunks: Chunk[]; chunkCount?:number; draftChunks?:Chunk[]; draftStatus?:string; status: 'ready' | 'indexing' | 'review' | 'failed' | 'disabled'; updatedAt: string; version: number; error?: string; warnings?:string[]; metadata?: DocMetadata; }
export interface ImportTask { id: string; traceId?: string; kbId: string; docId: string; name: string; progress: number; status: 'processing' | 'success' | 'failed' | 'cancelled' | 'review'; stage: string; autoPublish: boolean; time: string; error?: string; }
export interface LogStep { name: string; model: string; duration: number; tokens: number | null; status: string; }
export interface LogEntry { id: string; traceId?: string; question: string; answer: string; model: string; kbName: string; status: 'running' | 'success' | 'failed' | 'cancelled' | 'degraded'; tokens: number | null; inputTokens: number|null; outputTokens: number|null; duration: number; firstToken: number|null; time: string; role: string; source: 'chat' | 'retrieval' | 'import'; steps: LogStep[]; taskId?: string; documentId?: string; }
export interface ModelConfig { lastError?: string; id: string; name: string; modelId: string; provider: string; connectionId?:string; type: 'LLM' | 'Embedding' | 'Rerank' | 'Vision'; enabled: boolean; status: 'connected' | 'untested' | 'error'; dimension?: number; context?: number; }
export interface Connection { lastError?: string; id: string; provider: string; name: string; baseUrl: string; protocol: string; enabled: boolean; status: 'connected' | 'untested' | 'error'; keyConfigured: boolean; }
export interface SourceRef { docId: string; title: string; location: string; content: string; kind: 'text' | 'table' | 'image'; chunkId?:string; version?:number; assetUrl?:string; }
export interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; sources?: SourceRef[]; status?: 'complete' | 'cancelled' | 'failed'; feedback?: 'up' | 'down'; tokens?: number|null; duration?: number; }
export interface ChatSession { modelConfigId?: string; id: string; title: string; kbIds: string[]; messages: ChatMessage[]; updatedAt: string; }
export interface Settings { retention: number; batchLimit: number; fileLimit: number; chatConcurrency: number; importConcurrency: number; rerankRequired: boolean; }
