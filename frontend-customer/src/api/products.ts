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

export const listProducts = (params?: Record<string, unknown>) =>
  apiClient.get<PaginatedProducts>('/products', { params });

export const getProduct = (code: string) =>
  apiClient.get<ProductDetail>(`/products/${code}`);
