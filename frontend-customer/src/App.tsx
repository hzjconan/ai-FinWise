import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

import CustomerLayout from './components/CustomerLayout';
import Home from './pages/Home';
import ProductList from './pages/ProductList';
import ProductDetail from './pages/ProductDetail';
import AssessmentSelect from './pages/AssessmentSelect';
import AssessmentQuestionnaire from './pages/AssessmentQuestionnaire';
import AssessmentChat from './pages/AssessmentChat';
import AssessmentResultPage from './pages/AssessmentResult';
import Profile from './pages/Profile';

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<CustomerLayout />}>
            <Route index element={<Home />} />
            <Route path="products" element={<ProductList />} />
            <Route path="products/:code" element={<ProductDetail />} />
            <Route path="assessment" element={<AssessmentSelect />} />
            <Route path="assessment/questionnaire" element={<AssessmentQuestionnaire />} />
            <Route path="assessment/chat" element={<AssessmentChat />} />
            <Route path="assessment/result" element={<AssessmentResultPage />} />
            <Route path="profile" element={<Profile />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
