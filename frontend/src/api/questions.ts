import apiClient from './client';

export interface Option {
  id: number;
  content: string;
  score: number;
}

export interface Question {
  id: number;
  content: string;
  sort_order: number;
  is_active: boolean;
  options: Option[];
  created_at: string;
}

export const adminListQuestions = () =>
  apiClient.get<Question[]>('/admin/questions');

export const adminCreateQuestion = (data: Record<string, unknown>) =>
  apiClient.post<Question>('/admin/questions', data);

export const adminUpdateQuestion = (id: number, data: Record<string, unknown>) =>
  apiClient.put<Question>(`/admin/questions/${id}`, data);

export const adminDeleteQuestion = (id: number) =>
  apiClient.delete(`/admin/questions/${id}`);

export const adminSortQuestions = (orders: { id: number; sort_order: number }[]) =>
  apiClient.put('/admin/questions/sort', { orders });
