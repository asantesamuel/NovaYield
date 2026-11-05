import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ApiError, SESSION_EXPIRED_EVENT, api } from '../api/client';
import { AuthContext, type User } from './auth-context';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.get<User>('/auth/me')
      .then((currentUser) => { if (active) setUser(currentUser); })
      .catch((cause: unknown) => {
        // Missing or expired sessions are normal on a public login page.
        if (active && cause instanceof ApiError && cause.status !== 401) {
          setError(cause.message);
        }
      })
      .finally(() => { if (active) setIsInitialized(true); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const onSessionExpired = () => {
      setUser(null);
      setError('Your session expired. Please log in again.');
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
  }, []);

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    setError(null);
    try {
      await api.post<void>('/auth/login', { email, password });
      setUser(await api.get<User>('/auth/me'));
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Login failed.';
      setError(message);
      throw cause;
    } finally {
      setIsLoading(false);
    }
  };

  const signup = async (email: string, password: string) => {
    setIsLoading(true);
    setError(null);
    try {
      await api.post<User>('/auth/register', { email, password });
      await api.post<void>('/auth/login', { email, password });
      setUser(await api.get<User>('/auth/me'));
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Registration failed.';
      setError(message);
      throw cause;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    setError(null);
    try {
      await api.post<void>('/auth/logout');
      setUser(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setUser(null);
        return;
      }
      const message = cause instanceof Error ? cause.message : 'Logout failed.';
      setError(message);
      throw cause;
    }
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, isInitialized, error, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
