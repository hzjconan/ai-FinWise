import apiClient from './client';

export const createAnonymousCustomer = () =>
  apiClient.post<{ customer_code: string; is_registered: boolean }>(
    '/auth/customer/anonymous',
  );
