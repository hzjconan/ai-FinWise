import { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic } from 'antd';
import { ShoppingOutlined, FileTextOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { adminListProducts } from '../api/products';
import { adminListQuestions } from '../api/questions';

export default function Dashboard() {
  const [productCount, setProductCount] = useState(0);
  const [questionCount, setQuestionCount] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    adminListProducts({ page_size: 1 }).then(({ data }) => setProductCount(data.total));
    adminListQuestions().then(({ data }) => setQuestionCount(data.length));
  }, []);

  const clickableStyle = { cursor: 'pointer', color: '#1677ff' };

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>数据概览</h2>
      <Row gutter={16}>
        <Col span={8}>
          <Card hoverable onClick={() => navigate('/products')} data-testid="dashboard-products-card">
            <Statistic
              title="理财产品"
              value={productCount}
              prefix={<ShoppingOutlined />}
              valueStyle={clickableStyle}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card hoverable onClick={() => navigate('/questionnaire')} data-testid="dashboard-questions-card">
            <Statistic
              title="评估题目"
              value={questionCount}
              prefix={<FileTextOutlined />}
              valueStyle={clickableStyle}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
