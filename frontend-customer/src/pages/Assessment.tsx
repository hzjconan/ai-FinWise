import { useEffect, useState } from 'react';
import { Button, Card, Progress, Radio, Space, Spin, message } from 'antd';
import { useNavigate } from 'react-router-dom';
import { getActiveQuestions, submitAssessment } from '../api/assessment';
import type { Question } from '../api/assessment';
import { useAuthStore } from '../stores/authStore';

export default function Assessment() {
  const navigate = useNavigate();
  const customerCode = useAuthStore((s) => s.customerCode);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [current, setCurrent] = useState(0);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getActiveQuestions().then(({ data }) => {
      if (data.length === 0) {
        message.warning('暂无评估题目，请联系管理员');
        return;
      }
      setQuestions(data);
    });
  }, []);

  if (questions.length === 0) return <Spin style={{ display: 'block', margin: '40px auto' }} />;

  const q = questions[current];
  const progress = Math.round(((current + 1) / questions.length) * 100);

  const onSelect = (optionId: number) => {
    setAnswers((a) => ({ ...a, [q.id]: optionId }));
  };

  const onNext = () => {
    if (answers[q.id] == null) {
      message.warning('请选择一个选项');
      return;
    }
    if (current < questions.length - 1) {
      setCurrent(current + 1);
    }
  };

  const onPrev = () => {
    if (current > 0) setCurrent(current - 1);
  };

  const onSubmit = async () => {
    if (answers[q.id] == null) {
      message.warning('请选择一个选项');
      return;
    }
    if (!customerCode) {
      message.error('客户身份未初始化');
      return;
    }
    setSubmitting(true);
    try {
      const { data } = await submitAssessment({
        customer_code: customerCode,
        answers: questions.map((qq) => ({
          question_id: qq.id,
          option_id: answers[qq.id],
        })),
      });
      navigate('/assessment/result', { state: data });
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const isLast = current === questions.length - 1;

  return (
    <div>
      <Progress percent={progress} showInfo={false} style={{ marginBottom: 16 }} />
      <Card title={`第 ${current + 1} / ${questions.length} 题`}>
        <h3 style={{ marginBottom: 16 }}>{q.content}</h3>
        <Radio.Group
          value={answers[q.id]}
          onChange={(e) => onSelect(e.target.value)}
          style={{ width: '100%' }}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            {q.options.map((opt) => (
              <Radio
                key={opt.id}
                value={opt.id}
                style={{ display: 'block', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}
              >
                {opt.content}
              </Radio>
            ))}
          </Space>
        </Radio.Group>
        <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
          <Button onClick={onPrev} disabled={current === 0}>上一题</Button>
          {isLast ? (
            <Button type="primary" onClick={onSubmit} loading={submitting}>提交评估</Button>
          ) : (
            <Button type="primary" onClick={onNext}>下一题</Button>
          )}
        </div>
      </Card>
    </div>
  );
}
