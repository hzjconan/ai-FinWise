import { Layout, Menu, Button, theme } from 'antd';
import {
  DashboardOutlined,
  ShoppingOutlined,
  FileTextOutlined,
  LogoutOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';

const { Header, Sider, Content } = Layout;

const menuItems = [
  { key: '/admin/dashboard', icon: <DashboardOutlined />, label: 'Dashboard' },
  { key: '/admin/products', icon: <ShoppingOutlined />, label: '产品管理' },
  { key: '/admin/questionnaire', icon: <FileTextOutlined />, label: '问卷管理' },
];

export default function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const logoutAdmin = useAuthStore((s) => s.logoutAdmin);
  const { token: { colorBgContainer } } = theme.useToken();

  const selectedKey = menuItems.find((m) => location.pathname.startsWith(m.key))?.key ?? '';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider breakpoint="lg" collapsedWidth={0}>
        <div style={{ color: '#fff', textAlign: 'center', padding: '16px', fontSize: 18, fontWeight: 'bold' }}>
          FinWise 管理
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ background: colorBgContainer, padding: '0 24px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
          <Button
            icon={<LogoutOutlined />}
            onClick={() => { logoutAdmin(); navigate('/admin/login'); }}
          >
            退出
          </Button>
        </Header>
        <Content style={{ margin: 24, padding: 24, background: colorBgContainer, borderRadius: 8 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
