import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../context/auth-context';

export default function ProtectedRoute() {
  const { user, isInitialized } = useAuth();

  if (!isInitialized) {
    return <div className="page-container" role="status">Checking your session…</div>;
  }

  // Redirect to login if not authenticated
  if (!user) {
    return <Navigate to="/login" replace />;
  }

  // Render the protected child routes
  return <Outlet />;
}
