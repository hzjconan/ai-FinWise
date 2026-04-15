import { Layout, Menu, theme } from 'antd';
import {
  HomeOutlined,
  ShoppingOutlined,
  FormOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';

const { Header, Content, Footer } = Layout;

const menuItems = [
  { key: '/', icon: <HomeOutlined />, label: '首页' },
  { key: '/products', icon: <ShoppingOutlined />, label: '产品' },
  { key: '/assessment', icon: <FormOutlined />, label: '风险评估' },
  { key: '/profile', icon: <UserOutlined />, label: '我的' },
];

export default function CustomerLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { token: { colorBgContainer } } = theme.useToken();

  const selectedKey = menuItems.find((m) =>
    m.key === '/' ? location.pathname === '/' : location.pathname.startsWith(m.key),
  )?.key ?? '/';

  return (
    <Layout style={{ minHeight: '100vh', maxWidth: 480, margin: '0 auto', background: '#f5f5f5' }}>
      <Header style={{ background: colorBgContainer, textAlign: 'center', padding: 0 }}>
        <h2 style={{ margin: 0, lineHeight: '64px' }}>智财通 FinWise</h2>
      </Header>
      <Content style={{ padding: '16px', flex: 1 }}>
        <Outlet />
      </Content>
      <Footer style={{ padding: 0, position: 'sticky', bottom: 0 }}>
        <Menu
          mode="horizontal"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ display: 'flex', justifyContent: 'space-around' }}
        />
      </Footer>
    </Layout>
  );
}
