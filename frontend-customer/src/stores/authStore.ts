import { create } from 'zustand';

interface AuthState {
  customerCode: string | null;
  setCustomerCode: (code: string | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  customerCode: localStorage.getItem('customer_code'),
  setCustomerCode: (code) => {
    if (code) localStorage.setItem('customer_code', code);
    else localStorage.removeItem('customer_code');
    set({ customerCode: code });
  },
}));
