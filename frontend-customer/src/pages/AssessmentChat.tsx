import { useEffect, useRef, useState } from 'react';
import { Button, Card, Input, Result, Space, Spin, message as antMessage } from 'antd';
import { ReloadOutlined, SendOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import { restartChat, startChat, streamChatMessage } from '../api/chat';
import type { ChatMessageOut, ConcludedAssessment } from '../api/chat';
import { useAuthStore } from '../stores/authStore';

interface UIMessage {
  role: 'user' | 'assistant';
  content: string;
}

export default function AssessmentChat() {
  const navigate = useNavigate();
  const customerCode = useAuthStore((s) => s.customerCode);

  const [sessionCode, setSessionCode] = useState<string | null>(null);
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [starting, setStarting] = useState(true);
  const [round, setRound] = useState(0);
  const [input, setInput] = useState('');
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastUserContent, setLastUserContent] = useState<string | null>(null);

  const listRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (!customerCode) {
      setStarting(false);
      return;
    }
    // 守卫：StrictMode dev 下 effect 会跑两次，防止重复触发 /chat/start
    if (startedRef.current) return;
    startedRef.current = true;
    startChat(customerCode)
      .then(({ data }) => {
        setSessionCode(data.session_code);
        setMessages(
          data.messages.map((m: ChatMessageOut) => ({ role: m.role, content: m.content })),
        );
        setRound(data.messages.filter((m) => m.role === 'user').length);
      })
      .catch((err) => {
        antMessage.error(err.response?.data?.detail ?? '初始化失败');
      })
      .finally(() => setStarting(false));
  }, [customerCode]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, streamingContent]);

  const sendMessage = async (content: string) => {
    if (!sessionCode) return;
    setLastError(null);
    setLastUserContent(content);
    setMessages((prev) => [...prev, { role: 'user', content }]);
    setStreamingContent('');
    setStreaming(true);

    try {
      let acc = '';
      for await (const ev of streamChatMessage(sessionCode, content)) {
        if (ev.event === 'delta') {
          acc += ev.data.content;
          setStreamingContent(acc);
        } else if (ev.event === 'completed') {
          if (ev.data.phase === 'asking') {
            setMessages((prev) => [...prev, { role: 'assistant', content: acc }]);
            setStreamingContent('');
            setRound(ev.data.round);
          } else {
            // concluded
            const a: ConcludedAssessment = ev.data.assessment;
            navigate('/assessment/result', {
              state: {
                assessment_code: a.assessment_code,
                source: a.source,
                risk_preference: a.risk_preference,
                risk_label: a.risk_label,
                description: a.ai_summary ?? '',
                ai_summary: a.ai_summary,
                ai_dimensions: a.ai_dimensions,
              },
            });
            return;
          }
        } else if (ev.event === 'error') {
          setLastError(ev.data.message || '对话出错');
          // 回滚：用户消息保留在屏幕上，不加入 assistant 气泡
          setStreamingContent('');
          break;
        }
      }
    } catch (err: any) {
      setLastError(err.message ?? '网络错误');
      setStreamingContent('');
    } finally {
      setStreaming(false);
    }
  };

  const onSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    setInput('');
    void sendMessage(trimmed);
  };

  const onRetry = () => {
    if (!lastUserContent) return;
    // 去掉最后一条（尚未得到回复的）user 消息，重发
    setMessages((prev) => {
      const copy = [...prev];
      if (copy.length && copy[copy.length - 1].role === 'user') copy.pop();
      return copy;
    });
    void sendMessage(lastUserContent);
  };

  const onRestart = async () => {
    if (!sessionCode) return;
    setStreaming(true);
    setLastError(null);
    try {
      const { data } = await restartChat(sessionCode);
      setSessionCode(data.session_code);
      setMessages(data.messages.map((m) => ({ role: m.role, content: m.content })));
      setRound(0);
      setStreamingContent('');
    } catch (err: any) {
      antMessage.error(err.response?.data?.detail ?? '重新开始失败');
    } finally {
      setStreaming(false);
    }
  };

  if (starting) return <Spin style={{ display: 'block', margin: '40px auto' }} />;
  if (!customerCode) {
    return (
      <Result
        status="warning"
        title="客户身份未初始化"
        extra={<Button type="primary" onClick={() => navigate('/')}>回到首页</Button>}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 140px)' }}>
      <Card
        size="small"
        style={{ marginBottom: 8 }}
        bodyStyle={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
      >
        <span data-cy="chat-progress">已对话 {round} 轮 / 预计 5–8 轮</span>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={onRestart}
          disabled={streaming}
          data-cy="chat-restart"
        >
          重新开始
        </Button>
      </Card>

      <div
        ref={listRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 4px',
          background: '#fafafa',
          borderRadius: 8,
        }}
        data-cy="chat-messages"
      >
        {messages.map((m, i) => (
          <MessageBubble key={i} role={m.role} content={m.content} />
        ))}
        {streamingContent && <MessageBubble role="assistant" content={streamingContent} streaming />}
      </div>

      {lastError && (
        <div style={{ color: '#ff4d4f', margin: '8px 0', textAlign: 'center' }} data-cy="chat-error">
          {lastError}
          <Button type="link" size="small" onClick={onRetry} data-cy="chat-retry">
            重试
          </Button>
        </div>
      )}

      <Space.Compact style={{ width: '100%', marginTop: 8 }}>
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          placeholder="请输入您的回答..."
          autoSize={{ minRows: 1, maxRows: 4 }}
          disabled={streaming}
          data-cy="chat-input"
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={onSend}
          loading={streaming}
          disabled={!input.trim()}
          data-cy="chat-send"
        >
          发送
        </Button>
      </Space.Compact>
    </div>
  );
}

function MessageBubble({
  role,
  content,
  streaming,
}: {
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
}) {
  const isUser = role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        margin: '8px 0',
      }}
    >
      <div
        data-cy={isUser ? 'msg-user' : 'msg-assistant'}
        style={{
          maxWidth: '75%',
          padding: '8px 12px',
          borderRadius: 12,
          background: isUser ? '#1677ff' : '#fff',
          color: isUser ? '#fff' : '#000',
          border: isUser ? 'none' : '1px solid #f0f0f0',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {content}
        {streaming && <span style={{ opacity: 0.5 }}>▋</span>}
      </div>
    </div>
  );
}
