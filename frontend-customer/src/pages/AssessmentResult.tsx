import { useEffect, useState } from 'react';
import { Button, Card, List, Result, Typography } from 'antd';
import { useLocation, useNavigate } from 'react-router-dom';
import type { AssessmentResult, Recommendations, RecommendedProduct } from '../api/assessment';
import { getRecommendations } from '../api/assessment';
import { PreferenceBadge, RiskLevelBadge } from '../components/shared/RiskBadge';
import { useAuthStore } from '../stores/authStore';

const { Text } = Typography;

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

  const renderProduct = (p: RecommendedProduct) => (
    <Card
      size="small"
      style={{ marginBottom: 8, cursor: 'pointer' }}
      onClick={() => navigate(`/products/${p.product_code}`)}
      key={p.product_code}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Text strong>{p.name}</Text>
          <br />
          <Text type="secondary">{p.type}</Text>
          {p.match_type === 'conservative' && <Text type="secondary"> · 稍保守</Text>}
          {p.match_type === 'aggressive' && <Text type="secondary"> · 稍激进</Text>}
        </div>
        <div style={{ textAlign: 'right' }}>
          <Text style={{ fontSize: 16, color: '#cf1322' }}>
            {p.expected_return != null ? `${p.expected_return}%` : '-'}
          </Text>
          <br />
          <RiskLevelBadge level={p.risk_level} />
        </div>
      </div>
    </Card>
  );

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

      {recs && (
        <>
          {recs.exact_matches.length > 0 && (
            <>
              <h3 style={{ marginBottom: 8 }}>为您精选</h3>
              {recs.exact_matches.map(renderProduct)}
            </>
          )}
          {recs.adjacent_matches.length > 0 && (
            <>
              <h3 style={{ margin: '16px 0 8px' }}>您可能也感兴趣</h3>
              {recs.adjacent_matches.map(renderProduct)}
            </>
          )}
        </>
      )}
    </div>
  );
}
