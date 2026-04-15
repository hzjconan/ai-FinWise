import { create } from 'zustand';

interface AuthState {
  adminToken: string | null;
  setAdminToken: (token: string | null) => void;
  logoutAdmin: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  adminToken: localStorage.getItem('admin_token'),
  setAdminToken: (token) => {
    if (token) localStorage.setItem('admin_token', token);
    else localStorage.removeItem('admin_token');
    set({ adminToken: token });
  },
  logoutAdmin: () => {
    localStorage.removeItem('admin_token');
    set({ adminToken: null });
  },
}));
