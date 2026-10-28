import { Link, Outlet } from 'react-router-dom';

export default function Layout() {
  return (
    <div className="app-shell">
      <header style={{ padding: '1rem', borderBottom: '1px solid #ccc' }}>
        <Link to="/field" style={{ fontWeight: 'bold', textDecoration: 'none' }}>
          NovaYield
        </Link>
        {/* Logout button will go here in NY-25 */}
      </header>
      <main style={{ padding: '1rem' }}>
        <Outlet />
      </main>
    </div>
  );
}