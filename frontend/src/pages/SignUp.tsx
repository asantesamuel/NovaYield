import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function SignUp() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  
  const { signup, isLoading, error } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLocalError(null);

    if (password !== confirmPassword) {
      setLocalError('Passwords do not match.');
      return;
    }

    try {
      await signup(email, password);
      navigate('/field');
    } catch {
      // Error handled by context
    }
  };

  return (
    <div style={{ 
      display: 'flex', 
      justifyContent: 'center', 
      alignItems: 'center', 
      minHeight: '80vh' 
    }}>
      <div className="modal-card">
        <button 
          onClick={() => navigate('/')}
          style={{
            position: 'absolute',
            top: '1.5rem',
            right: '1.5rem',
            background: 'var(--line)',
            border: 'none',
            borderRadius: '50%',
            width: '32px',
            height: '32px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            color: 'var(--muted)'
          }}
          aria-label="Close"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M1 1L13 13M1 13L13 1" strokeLinecap="round"/>
          </svg>
        </button>

        <h2 style={{ fontSize: '1.5rem', marginBottom: '2rem', fontWeight: 600 }}>Create account</h2>
        
        {(error || localError) && (
          <p style={{ color: '#dc2626', fontSize: '0.875rem', marginBottom: '1rem' }}>
            {localError || error}
          </p>
        )}
        
        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label className="input-label">E-mail</label>
            <input 
              type="email" 
              value={email} 
              onChange={e => setEmail(e.target.value)} 
              className="input-field"
              placeholder="name@example.com"
              required 
            />
          </div>

          <div className="input-group">
            <label className="input-label">Password</label>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <input 
                type={showPassword ? 'text' : 'password'} 
                value={password} 
                onChange={e => setPassword(e.target.value)} 
                className="input-field"
                placeholder="••••••••"
                required 
              />
              <button 
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: '0.25rem',
                  cursor: 'pointer',
                  color: 'var(--muted)'
                }}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
              </button>
            </div>
          </div>

          <div className="input-group">
            <label className="input-label">Confirm Password</label>
            <input 
              type="password" 
              value={confirmPassword} 
              onChange={e => setConfirmPassword(e.target.value)} 
              className="input-field"
              placeholder="••••••••"
              required 
            />
          </div>

          <button type="submit" className="primary-button" disabled={isLoading}>
            {isLoading ? 'Creating...' : 'Sign Up'}
          </button>
        </form>
        
        <div style={{ marginTop: '2rem', textAlign: 'center', fontSize: '0.875rem', color: 'var(--muted)' }}>
          Already have an account? <Link to="/login" className="link-button" style={{ fontWeight: 600 }}>Log in</Link>
        </div>
      </div>
    </div>
  );
}
