import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import AdminLayout from './components/AdminLayout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import ProductList from './pages/ProductList';
import ProductEdit from './pages/ProductEdit';
import QuestionList from './pages/QuestionList';

import { useAuthStore } from './stores/authStore';

function AdminGuard({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.adminToken);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={<AdminGuard><AdminLayout /></AdminGuard>}
          >
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="products" element={<ProductList />} />
            <Route path="products/:code" element={<ProductEdit />} />
            <Route path="questionnaire" element={<QuestionList />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
