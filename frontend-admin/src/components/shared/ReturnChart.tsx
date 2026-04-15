import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import type { ReturnHistory } from '../../api/products';

export default function ReturnChart({ data }: { data: ReturnHistory[] }) {
  const chartData = data.map((d) => ({
    period: d.period_label,
    return_rate: Number(d.return_rate),
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="period" />
        <YAxis unit="%" />
        <Tooltip formatter={(value: number) => [`${value}%`, '收益率']} />
        <Line type="monotone" dataKey="return_rate" stroke="#1890ff" strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}
