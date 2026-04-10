import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import AdminLayout from './components/admin/AdminLayout';
import CustomerLayout from './components/customer/CustomerLayout';

import AdminLogin from './pages/admin/Login';
import Dashboard from './pages/admin/Dashboard';
import AdminProductList from './pages/admin/ProductList';
import AdminProductEdit from './pages/admin/ProductEdit';
import QuestionList from './pages/admin/QuestionList';

import Home from './pages/customer/Home';
import ProductList from './pages/customer/ProductList';
import ProductDetail from './pages/customer/ProductDetail';
import Assessment from './pages/customer/Assessment';
import AssessmentResultPage from './pages/customer/AssessmentResult';
import Profile from './pages/customer/Profile';

import { useAuthStore } from './stores/authStore';

function AdminGuard({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.adminToken);
  if (!token) return <Navigate to="/admin/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          {/* Admin */}
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route
            path="/admin"
            element={<AdminGuard><AdminLayout /></AdminGuard>}
          >
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="products" element={<AdminProductList />} />
            <Route path="products/:code" element={<AdminProductEdit />} />
            <Route path="questionnaire" element={<QuestionList />} />
          </Route>

          {/* Customer */}
          <Route path="/" element={<CustomerLayout />}>
            <Route index element={<Home />} />
            <Route path="products" element={<ProductList />} />
            <Route path="products/:code" element={<ProductDetail />} />
            <Route path="assessment" element={<Assessment />} />
            <Route path="assessment/result" element={<AssessmentResultPage />} />
            <Route path="profile" element={<Profile />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
