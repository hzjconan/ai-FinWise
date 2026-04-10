import { create } from 'zustand';

interface AuthState {
  adminToken: string | null;
  customerCode: string | null;
  setAdminToken: (token: string | null) => void;
  setCustomerCode: (code: string | null) => void;
  logoutAdmin: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  adminToken: localStorage.getItem('admin_token'),
  customerCode: localStorage.getItem('customer_code'),
  setAdminToken: (token) => {
    if (token) localStorage.setItem('admin_token', token);
    else localStorage.removeItem('admin_token');
    set({ adminToken: token });
  },
  setCustomerCode: (code) => {
    if (code) localStorage.setItem('customer_code', code);
    else localStorage.removeItem('customer_code');
    set({ customerCode: code });
  },
  logoutAdmin: () => {
    localStorage.removeItem('admin_token');
    set({ adminToken: null });
  },
}));
