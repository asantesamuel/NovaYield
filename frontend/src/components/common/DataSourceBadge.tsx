interface DataSourceBadgeProps {
  status: string;
  source: string;
  dateRange: string;
  resolution?: string | null;
  retrievedAt?: string | null;
}

export default function DataSourceBadge({ status, source, dateRange, resolution, retrievedAt }: DataSourceBadgeProps) {
  const label = status === 'live'
    ? 'Retrieved from NASA POWER'
    : status === 'cached'
      ? 'Reused stored NASA POWER data'
      : status === 'unavailable'
        ? 'NASA data unavailable'
        : `Data status: ${status.replaceAll('_', ' ')}`;

  return (
    <div className="source-badge">
      <strong>{label}</strong>
      <span>{source}</span>
      <span>Historical period: {dateRange}</span>
      {resolution && <span>Grid resolution: {resolution}</span>}
      {retrievedAt && <span>Retrieved: {new Date(retrievedAt).toLocaleString()}</span>}
    </div>
  );
}
