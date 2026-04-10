import { useEffect, useState } from 'react';
import { Card, Empty, List, Tabs, Tag, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { listFavorites, listAssessments, type FavoriteProduct, type AssessmentHistory } from '../../api/customers';
import { RiskLevelBadge, PreferenceBadge } from '../../components/shared/RiskBadge';
import { useAuthStore } from '../../stores/authStore';

const { Text } = Typography;

export default function Profile() {
  const navigate = useNavigate();
  const customerCode = useAuthStore((s) => s.customerCode);
  const [favorites, setFavorites] = useState<FavoriteProduct[]>([]);
  const [assessments, setAssessments] = useState<AssessmentHistory[]>([]);

  useEffect(() => {
    if (!customerCode) return;
    listFavorites(customerCode).then(({ data }) => setFavorites(data));
    listAssessments(customerCode).then(({ data }) => setAssessments(data));
  }, [customerCode]);

  if (!customerCode) {
    return <Empty description="暂无数据" />;
  }

  return (
    <div>
      <Card style={{ marginBottom: 16, textAlign: 'center' }}>
        <p style={{ color: '#999' }}>客户编号</p>
        <Text copyable>{customerCode}</Text>
      </Card>

      <Tabs
        items={[
          {
            key: 'assessments',
            label: `评估记录 (${assessments.length})`,
            children: assessments.length === 0 ? (
              <Empty description="暂无评估记录" />
            ) : (
              <List
                dataSource={assessments}
                renderItem={(a) => (
                  <Card size="small" style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <div>
                        <PreferenceBadge level={a.risk_preference} />
                        <Tag>{a.source === 'questionnaire' ? '问卷' : 'AI 对话'}</Tag>
                      </div>
                      <Text type="secondary">{new Date(a.created_at).toLocaleDateString()}</Text>
                    </div>
                  </Card>
                )}
              />
            ),
          },
          {
            key: 'favorites',
            label: `收藏 (${favorites.length})`,
            children: favorites.length === 0 ? (
              <Empty description="暂无收藏" />
            ) : (
              <List
                dataSource={favorites}
                renderItem={(p) => (
                  <Card
                    size="small"
                    style={{ marginBottom: 8, cursor: 'pointer' }}
                    onClick={() => navigate(`/products/${p.product_code}`)}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <div>
                        <Text strong>{p.name}</Text>
                        <br />
                        <Text type="secondary">{p.type}</Text>
                      </div>
                      <RiskLevelBadge level={p.risk_level} />
                    </div>
                  </Card>
                )}
              />
            ),
          },
        ]}
      />
    </div>
  );
}
