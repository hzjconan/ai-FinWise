import { useEffect, useState } from 'react';
import { Button, Table, Tag, Space, Select, message, Popconfirm } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { adminListProducts, adminUpdateStatus, type Product } from '../../api/products';
import { RiskLevelBadge } from '../../components/shared/RiskBadge';
import { PRODUCT_STATUS, PRODUCT_TYPES } from '../../utils/constants';

export default function AdminProductList() {
  const navigate = useNavigate();
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<Record<string, string>>({});

  const load = async (p = page) => {
    setLoading(true);
    try {
      const { data } = await adminListProducts({ page: p, page_size: 10, ...filters });
      setProducts(data.items);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(1); setPage(1); }, [filters]);

  const handleStatus = async (code: string, status: string) => {
    await adminUpdateStatus(code, status);
    message.success('状态已更新');
    load();
  };

  const columns = [
    { title: '产品编号', dataIndex: 'product_code', key: 'code' },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'type', key: 'type' },
    {
      title: '期望收益',
      dataIndex: 'expected_return',
      key: 'return',
      render: (v?: number) => v != null ? `${v}%` : '-',
    },
    {
      title: '风险等级',
      key: 'risk',
      render: (_: unknown, r: Product) => <RiskLevelBadge level={r.risk_level} />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => {
        const info = PRODUCT_STATUS[s];
        return <Tag color={info?.color}>{info?.label ?? s}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, r: Product) => (
        <Space>
          <a onClick={() => navigate(`/admin/products/${r.product_code}`)}>编辑</a>
          {r.status !== 'active' && (
            <Popconfirm title="确认上架？" onConfirm={() => handleStatus(r.product_code, 'active')}>
              <a>上架</a>
            </Popconfirm>
          )}
          {r.status === 'active' && (
            <Popconfirm title="确认下架？" onConfirm={() => handleStatus(r.product_code, 'inactive')}>
              <a>下架</a>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Select
            placeholder="产品类型"
            allowClear
            style={{ width: 120 }}
            onChange={(v) => setFilters((f) => ({ ...f, type: v }))}
            options={PRODUCT_TYPES.map((t) => ({ label: t, value: t }))}
          />
          <Select
            placeholder="状态"
            allowClear
            style={{ width: 100 }}
            onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
            options={Object.entries(PRODUCT_STATUS).map(([k, v]) => ({ label: v.label, value: k }))}
          />
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/admin/products/new')}>
          新增产品
        </Button>
      </div>
      <Table
        rowKey="product_code"
        columns={columns}
        dataSource={products}
        loading={loading}
        pagination={{ current: page, total, pageSize: 10, onChange: (p) => { setPage(p); load(p); } }}
      />
    </div>
  );
}
