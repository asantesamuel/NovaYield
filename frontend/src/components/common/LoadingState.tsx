export default function LoadingState({ message = "Loading data..." }: { message?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '3rem' }}>
      <div style={{
        width: '40px', height: '40px', border: '4px solid #e5e7eb', borderTop: '4px solid #047857',
        borderRadius: '50%', animation: 'spin 1s linear infinite'
      }} />
      <p style={{ marginTop: '1rem', color: '#6b7280', fontWeight: 500 }}>{message}</p>
      <style>
        {`@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }`}
      </style>
    </div>
  );
}