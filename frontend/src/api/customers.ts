import apiClient from './client';

export interface FavoriteProduct {
  product_code: string;
  name: string;
  type: string;
  expected_return?: number;
  risk_level?: string;
}

export interface AssessmentHistory {
  code: string;
  source: string;
  risk_preference: string;
  risk_label: string;
  ai_summary?: string;
  created_at: string;
}

export const listFavorites = (customerCode: string) =>
  apiClient.get<FavoriteProduct[]>(`/customers/${customerCode}/favorites`);

export const addFavorite = (customerCode: string, productCode: string) =>
  apiClient.post(`/customers/${customerCode}/favorites`, { product_code: productCode });

export const removeFavorite = (customerCode: string, productCode: string) =>
  apiClient.delete(`/customers/${customerCode}/favorites/${productCode}`);

export const listAssessments = (customerCode: string) =>
  apiClient.get<AssessmentHistory[]>(`/customers/${customerCode}/assessments`);
