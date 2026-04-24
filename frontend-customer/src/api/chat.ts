import apiClient from './client';

export interface ChatMessageOut {
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface ChatStartResponse {
  session_code: string;
  resumed: boolean;
  messages: ChatMessageOut[];
}

export interface ConcludedAssessment {
  assessment_code: string;
  source: 'ai_chat';
  risk_preference: string;
  risk_label: string;
  ai_summary?: string | null;
  ai_dimensions?: Record<string, number> | null;
}

export type SSEEvent =
  | { event: 'delta'; data: { content: string } }
  | { event: 'completed'; data: { phase: 'asking'; round: number } }
  | {
      event: 'completed';
      data: { phase: 'concluded'; round: number; assessment: ConcludedAssessment };
    }
  | { event: 'error'; data: { code: string; message: string } };

export const startChat = (customerCode: string) =>
  apiClient.post<ChatStartResponse>('/assessment/chat/start', { customer_code: customerCode });

export const restartChat = (sessionCode: string) =>
  apiClient.post<ChatStartResponse>(`/assessment/chat/${sessionCode}/restart`);

/**
 * 向会话发送用户消息，返回 SSE 事件的 async iterator。
 * 使用 fetch + ReadableStream（EventSource 不支持 POST body）。
 */
export async function* streamChatMessage(
  sessionCode: string,
  content: string,
): AsyncGenerator<SSEEvent> {
  const resp = await fetch(`/api/v1/assessment/chat/${sessionCode}/message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });

  if (!resp.ok || !resp.body) {
    let detail: string;
    try {
      detail = (await resp.json()).detail ?? resp.statusText;
    } catch {
      detail = resp.statusText;
    }
    throw new Error(detail || `HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE 事件以空行 (\n\n) 分隔
    let sepIdx: number;
    while ((sepIdx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);

      let eventName: string | null = null;
      let dataLine: string | null = null;
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) eventName = line.slice(7);
        else if (line.startsWith('data: ')) dataLine = line.slice(6);
      }
      if (eventName && dataLine !== null) {
        yield { event: eventName, data: JSON.parse(dataLine) } as SSEEvent;
      }
    }
  }
}
