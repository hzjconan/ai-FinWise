import { useEffect, useState } from 'react';
import { Card, List, Select, Space, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { listProducts, type Product } from '../api/products';
import { RiskLevelBadge } from '../components/shared/RiskBadge';
import { PRODUCT_TYPES, RISK_LEVEL_MAP } from '../utils/constants';

const { Text } = Typography;

export default function ProductList() {
  const navigate = useNavigate();
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Record<string, string>>({});

  const load = (p = page) => {
    listProducts({ page: p, page_size: 10, ...filters }).then(({ data }) => {
      setProducts(data.items);
      setTotal(data.total);
    });
  };

  useEffect(() => { load(1); setPage(1); }, [filters]);

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Select
          placeholder="类型"
          allowClear
          style={{ width: 100 }}
          onChange={(v) => setFilters((f) => ({ ...f, type: v }))}
          options={PRODUCT_TYPES.map((t) => ({ label: t, value: t }))}
        />
        <Select
          placeholder="风险等级"
          allowClear
          style={{ width: 110 }}
          onChange={(v) => setFilters((f) => ({ ...f, risk_level: v }))}
          options={Object.entries(RISK_LEVEL_MAP).map(([k, v]) => ({ label: v.label, value: k }))}
        />
      </Space>

      <List
        dataSource={products}
        pagination={{
          current: page, total, pageSize: 10, size: 'small',
          onChange: (p) => { setPage(p); load(p); },
        }}
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
                <Text type="secondary">{p.type} · 起投{p.min_investment}元</Text>
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
    </div>
  );
}
