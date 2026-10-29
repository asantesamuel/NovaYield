export default function DataSourceBadge({ 
  isLive, 
  source, 
  dateRange, 
  resolution 
}: { 
  isLive: boolean; 
  source: string; 
  dateRange: string; 
  resolution?: string; 
}) {
  const badgeStyle = {
    display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
    padding: '0.25rem 0.75rem', borderRadius: '9999px', fontSize: '0.75rem', fontWeight: 600,
    backgroundColor: isLive ? '#ecfdf5' : '#fffbeb',
    color: isLive ? '#047857' : '#b45309',
    border: `1px solid ${isLive ? '#a7f3d0' : '#fde68a'}`
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.875rem', color: '#6b7280' }}>
      <div>
        <span style={badgeStyle}>
          {isLive ? '● Live NASA Data' : '○ Cached Demo Data'}
        </span>
        <span style={{ marginLeft: '0.5rem' }}>{source}</span>
      </div>
      <div>
        Date Range: {dateRange} {resolution && `• Resolution: ${resolution}`}
      </div>
    </div>
  );
}