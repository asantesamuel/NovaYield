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
    <div className="auth-page">
      <div className="auth-left">
        <div className="auth-container">
          <Link to="/" className="auth-logo">
            NovaYield
          </Link>

          <div className="auth-header">
            <h1>Create account</h1>
            <p>Join NovaYield to start optimizing your fields.</p>
          </div>

          {(error || localError) && (
            <p style={{ color: '#dc2626', fontSize: '0.875rem', marginBottom: '1.5rem', fontWeight: 500 }}>
              {localError || error}
            </p>
          )}
          
          <form onSubmit={handleSubmit} className="form-grid" style={{ gridTemplateColumns: '1fr' }}>
            <div className="form-group">
              <label htmlFor="email">Email</label>
              <input 
                id="email"
                type="email" 
                value={email} 
                onChange={e => setEmail(e.target.value)} 
                className="form-input"
                placeholder="Your Email"
                required 
              />
            </div>

            <div className="form-group">
              <label htmlFor="password">Password</label>
              <div style={{ position: 'relative' }}>
                <input 
                  id="password"
                  type={showPassword ? 'text' : 'password'} 
                  value={password} 
                  onChange={e => setPassword(e.target.value)} 
                  className="form-input"
                  placeholder="Password"
                  style={{ paddingRight: '2.5rem' }}
                  required 
                />
                <button 
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={{
                    position: 'absolute',
                    right: '0.75rem',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'none',
                    border: 'none',
                    padding: '0.25rem',
                    cursor: 'pointer',
                    color: 'var(--text-muted)',
                    display: 'flex'
                  }}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                  </svg>
                </button>
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="confirm-password">Confirm Password</label>
              <input 
                id="confirm-password"
                type="password" 
                value={confirmPassword} 
                onChange={e => setConfirmPassword(e.target.value)} 
                className="form-input"
                placeholder="Confirm Password"
                required 
              />
            </div>

            <button type="submit" className="submit-btn" style={{ width: '100%', marginTop: '0.5rem' }} disabled={isLoading}>
              {isLoading ? 'Creating account...' : 'SIGN UP'}
            </button>
          </form>
          
          <div className="auth-footer">
            Already have an account? <Link to="/login" className="nav-link" style={{ color: 'var(--primary-color)', fontWeight: 600 }}>Log in</Link>
          </div>
        </div>
      </div>

      <div className="auth-right">
        <div className="brand-display">
          <h2>NovaYield</h2>
          <p>Precision AgTech. Global reach. Earth observed.</p>
        </div>
      </div>
    </div>
  );
}
