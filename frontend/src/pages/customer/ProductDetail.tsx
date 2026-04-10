import { useEffect, useState } from 'react';
import { Button, Card, Descriptions, Spin, message } from 'antd';
import { HeartOutlined, HeartFilled } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { getProduct, type ProductDetail as PD } from '../../api/products';
import { addFavorite, removeFavorite, listFavorites } from '../../api/customers';
import { RiskLevelBadge } from '../../components/shared/RiskBadge';
import ReturnChart from '../../components/shared/ReturnChart';
import { useAuthStore } from '../../stores/authStore';

export default function ProductDetail() {
  const { code } = useParams<{ code: string }>();
  const [product, setProduct] = useState<PD | null>(null);
  const [isFav, setIsFav] = useState(false);
  const customerCode = useAuthStore((s) => s.customerCode);

  useEffect(() => {
    if (code) {
      getProduct(code).then(({ data }) => setProduct(data));
    }
    if (customerCode) {
      listFavorites(customerCode).then(({ data }) => {
        setIsFav(data.some((f) => f.product_code === code));
      });
    }
  }, [code]);

  const toggleFav = async () => {
    if (!customerCode || !code) return;
    try {
      if (isFav) {
        await removeFavorite(customerCode, code);
        setIsFav(false);
        message.success('已取消收藏');
      } else {
        await addFavorite(customerCode, code);
        setIsFav(true);
        message.success('已收藏');
      }
    } catch {
      message.error('操作失败');
    }
  };

  if (!product) return <Spin style={{ display: 'block', margin: '40px auto' }} />;

  return (
    <div>
      <Card
        title={product.name}
        extra={
          <Button
            icon={isFav ? <HeartFilled style={{ color: '#f5222d' }} /> : <HeartOutlined />}
            onClick={toggleFav}
          >
            {isFav ? '已收藏' : '收藏'}
          </Button>
        }
      >
        <Descriptions column={1} size="small">
          <Descriptions.Item label="产品编号">{product.product_code}</Descriptions.Item>
          <Descriptions.Item label="类型">{product.type}</Descriptions.Item>
          <Descriptions.Item label="投资方向">{product.investment_direction ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="起投金额">{product.min_investment}元</Descriptions.Item>
          <Descriptions.Item label="投资期限">
            {product.investment_period ? `${product.investment_period}天` : '活期'}
          </Descriptions.Item>
          <Descriptions.Item label="期望收益率">
            {product.expected_return != null ? `${product.expected_return}%` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="风险等级">
            <RiskLevelBadge level={product.risk_level} />
          </Descriptions.Item>
        </Descriptions>
        {product.description && <p style={{ marginTop: 16 }}>{product.description}</p>}
      </Card>

      {product.return_histories.length > 0 && (
        <Card title="收益走势" style={{ marginTop: 16 }}>
          <ReturnChart data={product.return_histories} />
        </Card>
      )}
    </div>
  );
}
