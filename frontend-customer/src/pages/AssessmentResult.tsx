import { useEffect, useState } from 'react';
import { Button, Card, Result } from 'antd';
import { useLocation, useNavigate } from 'react-router-dom';
import type { AssessmentResult, Recommendations, RecommendedProduct } from '../api/assessment';
import { getRecommendations } from '../api/assessment';
import { PreferenceBadge } from '../components/shared/RiskBadge';
import ProductCard from '../components/shared/ProductCard';
import { useAuthStore } from '../stores/authStore';

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
