import { Tag } from 'antd';
import { RISK_LEVEL_MAP, PREFERENCE_MAP } from '../../utils/constants';

export function RiskLevelBadge({ level }: { level?: string }) {
  if (!level) return <Tag>未评估</Tag>;
  const info = RISK_LEVEL_MAP[level];
  return <Tag color={info?.color}>{info?.label ?? level}</Tag>;
}

export function PreferenceBadge({ level }: { level?: string }) {
  if (!level) return <Tag>未评估</Tag>;
  const info = PREFERENCE_MAP[level];
  return <Tag color={info?.color}>{info?.label ?? level}</Tag>;
}
