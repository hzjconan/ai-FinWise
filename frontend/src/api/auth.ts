import apiClient from './client';

export const adminLogin = (username: string, password: string) =>
  apiClient.post<{ access_token: string; token_type: string; expires_in: number }>(
    '/auth/admin/login',
    { username, password },
  );

export const createAnonymousCustomer = () =>
  apiClient.post<{ customer_code: string; is_registered: boolean }>(
    '/auth/customer/anonymous',
  );
