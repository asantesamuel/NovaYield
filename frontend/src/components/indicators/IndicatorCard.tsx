export interface IndicatorData {
  id: string;
  title: string;
  value: number;
  unit: string;
  description: string;
  threshold?: string; // Optional, e.g., "Threshold for heat stress: >35°C"
  source: string; // e.g., "NASA POWER"
  dateRange: string; // e.g., "2020-2021"
  calculationMethod: string; // For traceability
}

export default function IndicatorCard({ data }: { data: IndicatorData }) {
  return (
    <div className="indicator-card">
      <div className="indicator-title">{data.title}</div>
      
      <div className="indicator-value-row">
        <span className="indicator-value">{data.value}</span>
        <span className="indicator-unit">{data.unit}</span>
      </div>

      <div className="indicator-description">
        {data.description}
        {data.threshold && (
          <div className="indicator-threshold">
            <strong>Note:</strong> {data.threshold}
          </div>
        )}
      </div>

      <div className="indicator-footer">
        <span title={data.calculationMethod}>
          Source: {data.source}
        </span>
        <span>{data.dateRange}</span>
      </div>
    </div>
  );
}