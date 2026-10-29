export default function ErrorState({ 
  title = "Something went wrong", 
  message, 
  onRetry 
}: { 
  title?: string; 
  message: string; 
  onRetry?: () => void; 
}) {
  return (
    <div style={{ 
      padding: '2rem', backgroundColor: '#fef2f2', border: '1px solid #f87171', 
      borderRadius: '8px', textAlign: 'center', color: '#991b1b' 
    }}>
      <h3 style={{ margin: '0 0 0.5rem 0' }}>{title}</h3>
      <p style={{ margin: '0 0 1rem 0' }}>{message}</p>
      {onRetry && (
        <button onClick={onRetry} style={{ 
          padding: '0.5rem 1rem', backgroundColor: '#991b1b', color: 'white', 
          border: 'none', borderRadius: '4px', cursor: 'pointer' 
        }}>
          Try Again
        </button>
      )}
    </div>
  );
}