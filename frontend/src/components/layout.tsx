import { Link, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="app-shell" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <header style={{ 
        padding: '1rem 2rem', 
        borderBottom: '1px solid var(--line)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'var(--bg-page)'
      }}>
        <Link to="/" style={{ 
          fontWeight: 'bold', 
          textDecoration: 'none', 
          color: 'var(--forest)',
          fontSize: '1.25rem'
        }}>
          NovaYield
        </Link>
        
        <nav style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
          {user ? (
            <>
              <span style={{ fontSize: '0.875rem', color: 'var(--muted)' }}>{user.email}</span>
              <button 
                onClick={handleLogout}
                className="link-button"
                style={{ fontWeight: 500 }}
              >
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="link-button" style={{ fontWeight: 500 }}>Login</Link>
              <Link to="/signup" className="primary-button" style={{ 
                marginTop: 0, 
                padding: '0.5rem 1.25rem',
                fontSize: '0.875rem'
              }}>
                Get Started
              </Link>
            </>
          )}
        </nav>
      </header>
      
      <main style={{ flex: 1, padding: '2rem' }}>
        <Outlet />
      </main>
    </div>
  );
}
