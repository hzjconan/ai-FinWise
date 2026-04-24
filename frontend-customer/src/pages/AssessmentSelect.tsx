import { Card, Col, Row } from 'antd';
import { FormOutlined, MessageOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

export default function AssessmentSelect() {
  const navigate = useNavigate();

  const cardStyle: React.CSSProperties = {
    textAlign: 'center',
    cursor: 'pointer',
    height: '100%',
  };

  return (
    <div>
      <h2 style={{ marginBottom: 8 }}>开始风险评估</h2>
      <p style={{ color: '#666', marginBottom: 24 }}>
        请选择评估方式。两种方式最终都会给出您的风险偏好与产品推荐。
      </p>
      <Row gutter={16}>
        <Col span={12}>
          <Card
            hoverable
            style={cardStyle}
            onClick={() => navigate('/assessment/questionnaire')}
            data-cy="mode-questionnaire"
          >
            <FormOutlined style={{ fontSize: 40, color: '#1677ff', marginBottom: 12 }} />
            <h3>固定问卷</h3>
            <p style={{ color: '#666' }}>回答若干选择题，快速得到评估结果。</p>
          </Card>
        </Col>
        <Col span={12}>
          <Card
            hoverable
            style={cardStyle}
            onClick={() => navigate('/assessment/chat')}
            data-cy="mode-chat"
          >
            <MessageOutlined style={{ fontSize: 40, color: '#52c41a', marginBottom: 12 }} />
            <h3>AI 对话评估</h3>
            <p style={{ color: '#666' }}>通过 5–8 轮自然对话，更精准理解您的风险偏好。</p>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
