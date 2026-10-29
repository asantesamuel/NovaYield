import { useState } from 'react';
import { Link, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [logoutRequested, setLogoutRequested] = useState(false);

  const isAuthPage = location.pathname === '/login' || location.pathname === '/signup';
  const isLoggingOut = logoutRequested && !user && !isAuthPage;

  const handleLogout = () => {
    setLogoutRequested(true);
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="app-shell" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {!isAuthPage && !isLoggingOut && (
        <header style={{
          padding: '1rem 2rem',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          background: 'var(--bg-card)'
        }}>
          <Link to="/" style={{
            fontWeight: 'bold',
            textDecoration: 'none',
            color: 'var(--primary-color)',
            fontSize: '1.25rem'
          }}>
            NovaYield
          </Link>

          <nav style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
            {user ? (
              <>
                <span style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>{user.email}</span>
                <button
                  onClick={handleLogout}
                  className="logout-btn"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link to="/login" className="nav-link">Login</Link>
                <Link to="/signup" className="submit-btn" style={{
                  marginTop: 0,
                  padding: '0.5rem 1.25rem',
                  fontSize: '0.875rem',
                  textDecoration: 'none'
                }}>
                  Get Started
                </Link>
              </>
            )}
          </nav>
        </header>
      )}
      
      <main style={{ flex: 1, padding: isAuthPage ? 0 : '2rem' }}>
        <Outlet />
      </main>
    </div>
  );
}
