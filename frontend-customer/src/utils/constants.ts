export const RISK_LEVEL_MAP: Record<string, { label: string; color: string }> = {
  R1: { label: '低风险', color: '#52c41a' },
  R2: { label: '中低风险', color: '#73d13d' },
  R3: { label: '中风险', color: '#faad14' },
  R4: { label: '中高风险', color: '#fa8c16' },
  R5: { label: '高风险', color: '#f5222d' },
};

export const PREFERENCE_MAP: Record<string, { label: string; color: string }> = {
  C1: { label: '保守型', color: '#52c41a' },
  C2: { label: '稳健型', color: '#73d13d' },
  C3: { label: '平衡型', color: '#faad14' },
  C4: { label: '成长型', color: '#fa8c16' },
  C5: { label: '激进型', color: '#f5222d' },
};

export const PRODUCT_TYPES = ['货币基金', '债券', '股票', '混合', '另类'];

export const PRODUCT_STATUS: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  active: { label: '上架', color: 'success' },
  inactive: { label: '下架', color: 'error' },
};
