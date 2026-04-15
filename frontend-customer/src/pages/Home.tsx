import { useEffect, useState } from 'react';
import { Button, Card, List, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { listProducts, type Product } from '../api/products';
import { RiskLevelBadge } from '../components/shared/RiskBadge';
import { useAuthStore } from '../stores/authStore';
import { createAnonymousCustomer } from '../api/auth';

const { Text } = Typography;

export default function Home() {
  const navigate = useNavigate();
  const [products, setProducts] = useState<Product[]>([]);
  const customerCode = useAuthStore((s) => s.customerCode);
  const setCustomerCode = useAuthStore((s) => s.setCustomerCode);

  useEffect(() => {
    listProducts({ page_size: 6 }).then(({ data }) => setProducts(data.items));
    // Auto-create anonymous customer if not exists
    if (!customerCode) {
      createAnonymousCustomer().then(({ data }) => setCustomerCode(data.customer_code));
    }
  }, []);

  return (
    <div>
      <Card style={{ marginBottom: 16, textAlign: 'center' }}>
        <h3>不知道该买什么理财产品？</h3>
        <p style={{ color: '#666', marginBottom: 16 }}>完成风险评估，获取专属推荐</p>
        <Button type="primary" size="large" onClick={() => navigate('/assessment')}>
          开始风险评估
        </Button>
      </Card>

      <h3 style={{ marginBottom: 12 }}>热门产品</h3>
      <List
        dataSource={products}
        renderItem={(p) => (
          <Card
            size="small"
            style={{ marginBottom: 8, cursor: 'pointer' }}
            onClick={() => navigate(`/products/${p.product_code}`)}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <Text strong>{p.name}</Text>
                <br />
                <Text type="secondary">{p.type}</Text>
              </div>
              <div style={{ textAlign: 'right' }}>
                <Text style={{ fontSize: 18, color: '#cf1322' }}>
                  {p.expected_return != null ? `${p.expected_return}%` : '-'}
                </Text>
                <br />
                <RiskLevelBadge level={p.risk_level} />
              </div>
            </div>
          </Card>
        )}
      />
      <Button block onClick={() => navigate('/products')}>查看全部产品</Button>
    </div>
  );
}
