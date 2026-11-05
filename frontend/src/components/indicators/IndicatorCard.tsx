export interface IndicatorData {
  id: string;
  title: string;
  value: number | null;
  unit: string;
  description: string;
  status: string;
  source: string;
  dateRange: string;
  calculationMethod: string;
  coverage: string;
}

export default function IndicatorCard({ data }: { data: IndicatorData }) {
  return (
    <article className="indicator-card">
      <h3 className="indicator-title">{data.title}</h3>
      <div className="indicator-value-row">
        <span className="indicator-value">{data.value === null ? 'Not assessed' : data.value.toLocaleString()}</span>
        {data.value !== null && <span className="indicator-unit">{data.unit}</span>}
      </div>
      <p className="indicator-description">{data.description}</p>
      <p className="indicator-description"><strong>Status:</strong> {data.status.replaceAll('_', ' ')}</p>
      <div className="indicator-footer">
        <span title={data.calculationMethod}>Source: {data.source}</span>
        <span>{data.dateRange}</span>
      </div>
      <small>Coverage: {data.coverage}</small>
    </article>
  );
}
