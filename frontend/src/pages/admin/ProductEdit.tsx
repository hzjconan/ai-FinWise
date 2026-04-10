import { useEffect, useState } from 'react';
import {
  Button, Card, Form, Input, InputNumber, Select, message, Table, Space, DatePicker, Divider,
} from 'antd';
import { useNavigate, useParams } from 'react-router-dom';
import {
  adminGetProduct, adminCreateProduct, adminUpdateProduct, adminAddReturn, adminDeleteReturn,
  type ProductDetail, type ReturnHistory,
} from '../../api/products';
import { RiskLevelBadge } from '../../components/shared/RiskBadge';
import ReturnChart from '../../components/shared/ReturnChart';
import { PRODUCT_TYPES } from '../../utils/constants';
import dayjs from 'dayjs';

export default function AdminProductEdit() {
  const { code } = useParams<{ code: string }>();
  const isNew = code === 'new';
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [returnForm] = Form.useForm();
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isNew && code) {
      adminGetProduct(code).then(({ data }) => {
        setProduct(data);
        form.setFieldsValue(data);
      });
    }
  }, [code]);

  const onSave = async () => {
    const values = await form.validateFields();
    setLoading(true);
    try {
      if (isNew) {
        await adminCreateProduct(values);
        message.success('产品已创建');
        navigate('/admin/products');
      } else {
        const { product_code: _, ...updateData } = values;
        await adminUpdateProduct(code!, updateData);
        message.success('产品已更新');
      }
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '操作失败');
    } finally {
      setLoading(false);
    }
  };

  const onAddReturn = async () => {
    const values = await returnForm.validateFields();
    try {
      const { data } = await adminAddReturn(code!, {
        ...values,
        recorded_at: values.recorded_at.format('YYYY-MM-DD'),
      });
      message.success('收益记录已添加');
      returnForm.resetFields();
      // Refresh product
      const { data: updated } = await adminGetProduct(code!);
      setProduct(updated);
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '添加失败');
    }
  };

  const onDeleteReturn = async (returnId: number) => {
    await adminDeleteReturn(code!, returnId);
    message.success('已删除');
    const { data: updated } = await adminGetProduct(code!);
    setProduct(updated);
  };

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>{isNew ? '新增产品' : '编辑产品'}</h2>
      <Card>
        <Form form={form} layout="vertical" style={{ maxWidth: 600 }}>
          <Form.Item name="product_code" label="产品编号" rules={[{ required: true }]}>
            <Input disabled={!isNew} placeholder="如 WY-2025-001" />
          </Form.Item>
          <Form.Item name="name" label="产品名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="type" label="产品类型" rules={[{ required: true }]}>
            <Select options={PRODUCT_TYPES.map((t) => ({ label: t, value: t }))} />
          </Form.Item>
          <Form.Item name="investment_direction" label="投资方向">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="min_investment" label="起投金额（元）">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="investment_period" label="投资期限（天）">
            <InputNumber min={0} style={{ width: '100%' }} placeholder="留空表示活期" />
          </Form.Item>
          <Form.Item name="description" label="产品描述">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" onClick={onSave} loading={loading}>保存</Button>
              <Button onClick={() => navigate('/admin/products')}>返回</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {!isNew && product && (
        <>
          <Divider />
          <Card
            title="风险指标"
            extra={<RiskLevelBadge level={product.risk_level} />}
            style={{ marginBottom: 16 }}
          >
            <p>期望收益率: {product.expected_return != null ? `${product.expected_return}%` : '待计算'}</p>
            <p>收益率标准差: {product.return_stddev != null ? `${product.return_stddev}%` : '待计算'}</p>
          </Card>

          <Card title="历史收益数据" style={{ marginBottom: 16 }}>
            {product.return_histories.length > 0 && <ReturnChart data={product.return_histories} />}
            <Table
              rowKey="id"
              dataSource={product.return_histories}
              size="small"
              pagination={false}
              columns={[
                { title: '期次', dataIndex: 'period_label' },
                { title: '收益率(%)', dataIndex: 'return_rate' },
                { title: '日期', dataIndex: 'recorded_at' },
                {
                  title: '操作',
                  render: (_: unknown, r: ReturnHistory) => (
                    <a onClick={() => onDeleteReturn(r.id)}>删除</a>
                  ),
                },
              ]}
            />
            <Divider orientation="left">添加收益记录</Divider>
            <Form form={returnForm} layout="inline" onFinish={onAddReturn}>
              <Form.Item name="period_label" rules={[{ required: true }]}>
                <Input placeholder="期次，如 2024-Q3" />
              </Form.Item>
              <Form.Item name="return_rate" rules={[{ required: true }]}>
                <InputNumber placeholder="收益率(%)" step={0.01} />
              </Form.Item>
              <Form.Item name="recorded_at" rules={[{ required: true }]}>
                <DatePicker placeholder="记录日期" />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit">添加</Button>
              </Form.Item>
            </Form>
          </Card>
        </>
      )}
    </div>
  );
}
