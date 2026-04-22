import { useEffect, useState } from 'react';
import { Button, Table, Tag, Space, Select, message, Popconfirm } from 'antd';
import type { TableProps } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { adminListProducts, adminUpdateStatus, type Product } from '../api/products';
import { RiskLevelBadge } from '../components/shared/RiskBadge';
import { PRODUCT_STATUS, PRODUCT_TYPES, RISK_LEVEL_MAP } from '../utils/constants';

export default function AdminProductList() {
  const navigate = useNavigate();
  const [products, setProducts] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<{ sort_by?: string; sort_order?: 'asc' | 'desc' }>({});
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    adminListProducts({ page, page_size: 10, ...filters, ...sort })
      .then(({ data }) => {
        if (cancelled) return;
        setProducts(data.items);
        setTotal(data.total);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [page, filters, sort, refreshTick]);

  useEffect(() => { setPage(1); }, [filters]);

  const handleTableChange: TableProps<Product>['onChange'] = (pag, _flt, sorter) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    const nextSortBy = s?.order && s.columnKey ? String(s.columnKey) : undefined;
    const nextSortOrder: 'asc' | 'desc' | undefined =
      s?.order === 'ascend' ? 'asc' : s?.order === 'descend' ? 'desc' : undefined;
    const sortChanged =
      nextSortBy !== sort.sort_by || nextSortOrder !== sort.sort_order;

    if (sortChanged) {
      setSort(nextSortBy ? { sort_by: nextSortBy, sort_order: nextSortOrder } : {});
      setPage(1);
    } else if (pag.current && pag.current !== page) {
      setPage(pag.current);
    }
  };

  const handleStatus = async (code: string, status: string) => {
    await adminUpdateStatus(code, status);
    message.success('状态已更新');
    setRefreshTick((t) => t + 1);
  };

  const columns: TableProps<Product>['columns'] = [
    { title: '产品编号', dataIndex: 'product_code', key: 'product_code', sorter: true },
    { title: '名称', dataIndex: 'name', key: 'name', sorter: true },
    { title: '类型', dataIndex: 'type', key: 'type' },
    {
      title: '期望收益',
      dataIndex: 'expected_return',
      key: 'expected_return',
      sorter: true,
      render: (v?: number) => v != null ? `${v}%` : '-',
    },
    {
      title: '风险等级',
      key: 'risk_level',
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
          <a onClick={() => navigate(`/products/${r.product_code}`)}>编辑</a>
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
          <Select
            placeholder="风险等级"
            allowClear
            style={{ width: 140 }}
            onChange={(v) => setFilters((f) => ({ ...f, risk_level: v }))}
            options={Object.entries(RISK_LEVEL_MAP).map(([k, v]) => ({
              label: `${k} · ${v.label}`,
              value: k,
            }))}
          />
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/products/new')}>
          新增产品
        </Button>
      </div>
      <Table
        rowKey="product_code"
        columns={columns}
        dataSource={products}
        loading={loading}
        onChange={handleTableChange}
        pagination={{
          current: page,
          total,
          pageSize: 10,
          showTotal: (t, [from, to]) => `第 ${from}-${to} 条 / 共 ${t} 条`,
        }}
      />
    </div>
  );
}
