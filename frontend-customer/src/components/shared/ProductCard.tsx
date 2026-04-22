import { Card, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { RiskLevelBadge } from './RiskBadge';

const { Text } = Typography;

export interface ProductCardData {
  product_code: string;
  name: string;
  type: string;
  expected_return?: number;
  risk_level?: string;
}

interface Props {
  product: ProductCardData;
  extraLabel?: string;
}

export default function ProductCard({ product, extraLabel }: Props) {
  const navigate = useNavigate();
  return (
    <Card
      size="small"
      style={{ marginBottom: 8, cursor: 'pointer' }}
      onClick={() => navigate(`/products/${product.product_code}`)}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Text strong>{product.name}</Text>
          <br />
          <Text type="secondary">{product.type}</Text>
          {extraLabel && <Text type="secondary"> · {extraLabel}</Text>}
        </div>
        <div style={{ textAlign: 'right' }}>
          <Text style={{ fontSize: 18, color: '#cf1322' }}>
            {product.expected_return != null ? `${product.expected_return}%` : '-'}
          </Text>
          <br />
          <RiskLevelBadge level={product.risk_level} />
        </div>
      </div>
    </Card>
  );
}
