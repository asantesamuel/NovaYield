import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const { login, isLoading, error } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await login(email, password);
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
            <h1>Log in</h1>
            <p>Welcome back! Please enter your details.</p>
          </div>

          {error && <p style={{ color: '#dc2626', fontSize: '0.875rem', marginBottom: '1.5rem', fontWeight: 500 }}>{error}</p>}

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

            <button type="submit" className="submit-btn" style={{ width: '100%', marginTop: '0.5rem' }} disabled={isLoading}>
              {isLoading ? 'Logging in...' : 'LOGIN'}
            </button>
          </form>

          <div className="auth-footer">
            Don't have an account? <Link to="/signup" className="nav-link" style={{ color: 'var(--primary-color)', fontWeight: 600 }}>Sign up</Link>
          </div>
        </div>
      </div>

      <div className="auth-right">
        <div className="brand-display">
          <h2>NovaYield</h2>
          <p>Next-gen AgTech powered by NASA Earth observations.</p>
        </div>
      </div>
    </div>
  );
}
