import IndicatorCard from '../components/indicators/IndicatorCard';
import type { IndicatorData } from '../components/indicators/IndicatorCard';
import DataSourceBadge from '../components/common/DataSourceBadge';

// Mock data based on the PRD requirements for the pilot zone
const MOCK_INDICATORS: IndicatorData[] = [
  {
    id: 'precip-1',
    title: 'Seasonal Precipitation',
    value: 412.5,
    unit: 'mm',
    description: 'Cumulative rainfall over the primary maize growing season. Lower than the 10-year average for the region.',
    source: 'NASA POWER (PRECTOTCORR)',
    dateRange: 'Apr 2025 - Oct 2025',
    calculationMethod: 'Sum of daily corrected precipitation.'
  },
  {
    id: 'temp-1',
    title: 'Mean Maximum Temperature',
    value: 34.2,
    unit: '°C',
    description: 'Average daily maximum temperature during the flowering stage, indicating potential heat stress risk.',
    threshold: 'Heat stress threshold for maize is typically >32°C during flowering.',
    source: 'NASA POWER (T2M_MAX)',
    dateRange: 'Jul 2025 - Aug 2025',
    calculationMethod: 'Average of daily maximum temperatures at 2m.'
  }
];

export default function Comparison() {
  return (
    <div className="page-container" style={{ maxWidth: '1000px' }}>
      
      <div style={{ marginBottom: '2rem' }}>
        <h2 style={{ marginBottom: '1rem' }}>Environmental Context</h2>
        <DataSourceBadge 
          isLive={false} 
          source="NASA POWER (Cached)" 
          dateRange="Apr 2025 - Oct 2025" 
          resolution="0.5° x 0.625°" 
        />
      </div>

      {/* Indicators Grid */}
      <div className="indicators-grid">
        {MOCK_INDICATORS.map(indicator => (
          <IndicatorCard key={indicator.id} data={indicator} />
        ))}
      </div>

      {/* Next up: NY-29 Comparison Dashboard */}
      <div style={{ marginTop: '3rem', padding: '2rem', textAlign: 'center', border: '1px dashed #ccc', borderRadius: '8px' }}>
        <h3>Rotation Options Comparison</h3>
        <p style={{ color: '#666' }}>Coming in NY-29...</p>
      </div>

    </div>
  );
}