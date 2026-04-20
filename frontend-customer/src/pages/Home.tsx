import { useEffect, useRef, useState } from 'react';
import { Button, Card, List, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { listProducts, type Product } from '../api/products';
import { RiskLevelBadge } from '../components/shared/RiskBadge';
import { useAuthStore } from '../stores/authStore';
import { createAnonymousCustomer } from '../api/auth';
import apiClient from '../api/client';

const { Text } = Typography;

export default function Home() {
  const navigate = useNavigate();
  const [products, setProducts] = useState<Product[]>([]);
  const customerCode = useAuthStore((s) => s.customerCode);
  const setCustomerCode = useAuthStore((s) => s.setCustomerCode);

  // 防止 React StrictMode 开发模式下 useEffect 双重执行导致重复创建匿名客户
  const customerInitRef = useRef(false);

  useEffect(() => {
    listProducts({ page_size: 6 }).then(({ data }) => setProducts(data.items));

    if (customerInitRef.current) return;
    customerInitRef.current = true;

    // 确保匿名客户身份有效。
    // customerCode 保存在 localStorage 中，但后端数据库可能已重建（如开发阶段重置 DB），
    // 导致 localStorage 里的旧 customerCode 在后端已不存在。
    // 因此即使 localStorage 有值，也需要向后端验证，无效则清除并重新创建。
    const ensureCustomer = async () => {
      if (customerCode) {
        try {
          await apiClient.get(`/customers/${customerCode}/assessments`);
          return; // 客户存在，无需操作
        } catch {
          setCustomerCode(null); // 客户不存在，清除过期的 code
        }
      }
      const { data } = await createAnonymousCustomer();
      setCustomerCode(data.customer_code);
    };
    ensureCustomer();
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
