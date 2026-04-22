import { useEffect, useRef, useState } from 'react';
import { Button, Card, Empty, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { getHotProducts, type Product } from '../api/products';
import { getRecommendations, type Recommendations } from '../api/assessment';
import { PreferenceBadge } from '../components/shared/RiskBadge';
import ProductCard from '../components/shared/ProductCard';
import { useAuthStore } from '../stores/authStore';
import { createAnonymousCustomer } from '../api/auth';
import apiClient from '../api/client';

const { Text } = Typography;

interface AssessmentHistoryItem {
  code: string;
  risk_preference: string;
  risk_label: string;
  created_at: string;
}

export default function Home() {
  const navigate = useNavigate();
  const [hot, setHot] = useState<Product[]>([]);
  const [recs, setRecs] = useState<Recommendations | null>(null);
  const [latestAssessment, setLatestAssessment] = useState<AssessmentHistoryItem | null>(null);
  const [ready, setReady] = useState(false);
  const customerCode = useAuthStore((s) => s.customerCode);
  const setCustomerCode = useAuthStore((s) => s.setCustomerCode);

  const customerInitRef = useRef(false);

  useEffect(() => {
    getHotProducts().then(({ data }) => setHot(data.items));

    if (customerInitRef.current) return;
    customerInitRef.current = true;

    const fetchAssessments = async (c: string) =>
      apiClient.get<AssessmentHistoryItem[]>(`/customers/${c}/assessments`);

    const init = async () => {
      let code = customerCode;
      let assessments: AssessmentHistoryItem[] = [];

      if (code) {
        try {
          const { data } = await fetchAssessments(code);
          assessments = data;
        } catch {
          setCustomerCode(null);
          code = null;
        }
      }

      if (!code) {
        const { data } = await createAnonymousCustomer();
        setCustomerCode(data.customer_code);
        code = data.customer_code;
        try {
          const { data: list } = await fetchAssessments(code);
          assessments = list;
        } catch {
          assessments = [];
        }
      }

      setLatestAssessment(assessments[0] ?? null);

      if (assessments.length > 0 && code) {
        try {
          const { data } = await getRecommendations(code);
          setRecs(data);
        } catch {
          // No assessment yet — leave recs null
        }
      }
      setReady(true);
    };
    init();
  }, []);

  const hasAssessed = !!latestAssessment;
  const recProducts = recs ? [...recs.exact_matches, ...recs.adjacent_matches] : [];
  const recCodes = new Set(recProducts.map((p) => p.product_code));
  const hotFiltered = hot.filter((p) => !recCodes.has(p.product_code));

  return (
    <div>
      {!ready ? null : hasAssessed ? (
        <Card style={{ marginBottom: 16, textAlign: 'center' }}>
          <div style={{ marginBottom: 8 }}>
            <Text type="secondary">当前风险偏好：</Text>
            <PreferenceBadge level={latestAssessment!.risk_preference} />
            <Text> {latestAssessment!.risk_label}</Text>
          </div>
          <p style={{ color: '#666', marginBottom: 16 }}>偏好或情况有变？可再次评估以更新推荐</p>
          <Button type="primary" onClick={() => navigate('/assessment')}>
            重新评估
          </Button>
        </Card>
      ) : (
        <Card style={{ marginBottom: 16, textAlign: 'center' }}>
          <h3>不知道该买什么理财产品？</h3>
          <p style={{ color: '#666', marginBottom: 16 }}>完成风险评估，获取专属推荐</p>
          <Button type="primary" size="large" onClick={() => navigate('/assessment')}>
            开始风险评估
          </Button>
        </Card>
      )}

      {hasAssessed && (
        <>
          <h3 style={{ marginBottom: 12 }}>为您推荐</h3>
          {recProducts.length > 0 ? (
            recProducts.map((p) => (
              <ProductCard
                key={p.product_code}
                product={p}
                extraLabel={
                  p.match_type === 'conservative'
                    ? '稍保守'
                    : p.match_type === 'aggressive'
                      ? '稍激进'
                      : undefined
                }
              />
            ))
          ) : (
            <Empty
              description="暂无合适的理财产品，建议查看热门产品或联系理财经理"
              style={{ marginBottom: 16 }}
            />
          )}
        </>
      )}

      <h3 style={{ margin: '16px 0 12px' }}>热门产品</h3>
      {hotFiltered.length > 0 ? (
        hotFiltered.map((p) => <ProductCard key={p.product_code} product={p} />)
      ) : (
        <Empty description="暂无热门产品" style={{ marginBottom: 16 }} />
      )}

      <Button block onClick={() => navigate('/products')}>
        查看全部产品
      </Button>
    </div>
  );
}
