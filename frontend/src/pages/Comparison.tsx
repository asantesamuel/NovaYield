import LoadingState from '../components/common/LoadingState';
import ErrorState from '../components/common/ErrorState';
import DataSourceBadge from '../components/common/DataSourceBadge';

export default function Comparison() {
  return (
    <div style={{ padding: '2rem', display: 'flex', flexDirection: 'column', gap: '2rem' }}>
      <h1>Comparison Page (Placeholder)</h1>
      
      <DataSourceBadge isLive={true} source="NASA POWER" dateRange="Jan 2020 - Dec 2020" resolution="0.5° x 0.5°" />
      <DataSourceBadge isLive={false} source="NASA POWER" dateRange="Jan 2021 - Dec 2021" resolution="0.5° x 0.5°" />
      
      <LoadingState message="Fetching NASA POWER data..." />
      
      <ErrorState 
        message="Failed to connect to NASA API. Please check your connection." 
        onRetry={() => alert('Retry clicked')} 
      />
    </div>
  );
}