import apiClient from './client';

export interface Product {
  product_code: string;
  name: string;
  type: string;
  investment_direction?: string;
  min_investment: number;
  investment_period?: number;
  description?: string;
  status: string;
  expected_return?: number;
  return_stddev?: number;
  risk_level?: string;
  created_at: string;
}

export interface ReturnHistory {
  id: number;
  period_label: string;
  return_rate: number;
  recorded_at: string;
}

export interface ProductDetail extends Product {
  updated_at: string;
  return_histories: ReturnHistory[];
}

export interface PaginatedProducts {
  total: number;
  page: number;
  page_size: number;
  items: Product[];
}

export const adminListProducts = (params?: Record<string, unknown>) =>
  apiClient.get<PaginatedProducts>('/admin/products', { params });

export const adminGetProduct = (code: string) =>
  apiClient.get<ProductDetail>(`/admin/products/${code}`);

export const adminCreateProduct = (data: Record<string, unknown>) =>
  apiClient.post<Product>('/admin/products', data);

export const adminUpdateProduct = (code: string, data: Record<string, unknown>) =>
  apiClient.put<Product>(`/admin/products/${code}`, data);

export const adminUpdateStatus = (code: string, status: string) =>
  apiClient.patch<Product>(`/admin/products/${code}/status`, { status });

export const adminAddReturn = (code: string, data: Record<string, unknown>) =>
  apiClient.post(`/admin/products/${code}/returns`, data);

export const adminDeleteReturn = (code: string, returnId: number) =>
  apiClient.delete(`/admin/products/${code}/returns/${returnId}`);
