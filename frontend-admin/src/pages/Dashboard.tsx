import { useEffect, useState } from 'react';
import { Card, Col, Row, Statistic } from 'antd';
import { ShoppingOutlined, FileTextOutlined } from '@ant-design/icons';
import { adminListProducts } from '../api/products';
import { adminListQuestions } from '../api/questions';

export default function Dashboard() {
  const [productCount, setProductCount] = useState(0);
  const [questionCount, setQuestionCount] = useState(0);

  useEffect(() => {
    adminListProducts({ page_size: 1 }).then(({ data }) => setProductCount(data.total));
    adminListQuestions().then(({ data }) => setQuestionCount(data.length));
  }, []);

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>数据概览</h2>
      <Row gutter={16}>
        <Col span={8}>
          <Card>
            <Statistic title="理财产品" value={productCount} prefix={<ShoppingOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="评估题目" value={questionCount} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
