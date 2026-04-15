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

export interface AssessmentResult {
  assessment_code: string;
  source: string;
  total_score?: number;
  normalized_score?: number;
  risk_preference: string;
  risk_label: string;
  description: string;
}

export interface RecommendedProduct {
  product_code: string;
  name: string;
  type: string;
  expected_return?: number;
  risk_level?: string;
  match_type: string;
}

export interface Recommendations {
  risk_preference: string;
  risk_label: string;
  exact_matches: RecommendedProduct[];
  adjacent_matches: RecommendedProduct[];
}

export const getActiveQuestions = () =>
  apiClient.get<Question[]>('/assessment/questions');

export const submitAssessment = (data: {
  customer_code: string;
  answers: { question_id: number; option_id: number }[];
}) => apiClient.post<AssessmentResult>('/assessment/submit', data);

export const getRecommendations = (customerCode: string) =>
  apiClient.get<Recommendations>('/recommendations', {
    params: { customer_code: customerCode },
  });
