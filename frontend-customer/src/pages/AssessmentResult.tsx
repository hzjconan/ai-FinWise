import { useEffect, useState } from 'react';
import { Button, Card, Progress, Result } from 'antd';
import { useLocation, useNavigate } from 'react-router-dom';
import type { AssessmentResult, Recommendations, RecommendedProduct } from '../api/assessment';
import { getRecommendations } from '../api/assessment';
import { PreferenceBadge } from '../components/shared/RiskBadge';
import ProductCard from '../components/shared/ProductCard';
import { useAuthStore } from '../stores/authStore';

const DIMENSION_LABELS: Record<string, string> = {
  experience: '投资经验',
  loss_tolerance: '损失承受',
  income_stability: '收入稳定性',
  investment_horizon: '投资期限',
  volatility_tolerance: '波动态度',
};

export default function AssessmentResultPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const result = location.state as AssessmentResult | undefined;
  const customerCode = useAuthStore((s) => s.customerCode);
  const [recs, setRecs] = useState<Recommendations | null>(null);

  useEffect(() => {
    if (customerCode) {
      getRecommendations(customerCode).then(({ data }) => setRecs(data)).catch(() => {});
    }
  }, [customerCode]);

  if (!result) {
    return (
      <Result
        status="info"
        title="请先完成风险评估"
        extra={<Button type="primary" onClick={() => navigate('/assessment')}>开始评估</Button>}
      />
    );
  }

  const extraLabel = (p: RecommendedProduct) =>
    p.match_type === 'conservative'
      ? '稍保守'
      : p.match_type === 'aggressive'
        ? '稍激进'
        : undefined;

  return (
    <div>
      <Card style={{ textAlign: 'center', marginBottom: 16 }}>
        <h2>您的风险偏好</h2>
        <div style={{ fontSize: 48, margin: '16px 0' }}>
          <PreferenceBadge level={result.risk_preference} />
        </div>
        <h3>{result.risk_label}</h3>
        <p style={{ color: '#666', marginTop: 8 }}>{result.description}</p>
        <Button style={{ marginTop: 16 }} onClick={() => navigate('/assessment')}>
          重新评估
        </Button>
      </Card>

      {result.source === 'ai_chat' && result.ai_summary && (
        <Card title="AI 评估摘要" style={{ marginBottom: 16 }} data-cy="ai-summary">
          <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{result.ai_summary}</p>
        </Card>
      )}

      {result.source === 'ai_chat' && result.ai_dimensions && (
        <Card title="评估维度" style={{ marginBottom: 16 }} data-cy="ai-dimensions">
          {Object.entries(DIMENSION_LABELS).map(([key, label]) => {
            const score = result.ai_dimensions?.[key];
            if (typeof score !== 'number') return null;
            return (
              <div
                key={key}
                style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}
                data-cy={`ai-dim-${key}`}
              >
                <div style={{ width: 96, color: '#666' }}>{label}</div>
                <Progress
                  percent={score * 20}
                  showInfo={false}
                  strokeColor="#52c41a"
                  style={{ flex: 1, margin: 0 }}
                />
                <div style={{ width: 24, textAlign: 'right' }}>{score}</div>
              </div>
            );
          })}
        </Card>
      )}

      {recs && (
        <>
          {recs.exact_matches.length > 0 && (
            <>
              <h3 style={{ marginBottom: 8 }}>为您精选</h3>
              {recs.exact_matches.map((p) => (
                <ProductCard key={p.product_code} product={p} extraLabel={extraLabel(p)} />
              ))}
            </>
          )}
          {recs.adjacent_matches.length > 0 && (
            <>
              <h3 style={{ margin: '16px 0 8px' }}>您可能也感兴趣</h3>
              {recs.adjacent_matches.map((p) => (
                <ProductCard key={p.product_code} product={p} extraLabel={extraLabel(p)} />
              ))}
            </>
          )}
        </>
      )}
    </div>
  );
}
