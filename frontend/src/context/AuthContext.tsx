import { createContext, useContext, useState } from 'react';
import type { ReactNode } from 'react';

// Define the shape of our user
export interface User {
  id: string;
  email: string;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // --- MOCK API CALLS (Replace with real api.post later) ---
  const mockApiCall = (email: string, password: string) => {
    return new Promise<void>((resolve, reject) => {
      setTimeout(() => {
        // Mock validation: fail if password is too short
        if (password.length < 6) {
          reject(new Error('Password must be at least 6 characters.'));
        } 
        // Mock duplicate email
        else if (email === 'test@novayield.com' && password === 'password') {
          reject(new Error('Email already in use.'));
        } 
        // Success
        else {
          resolve();
        }
      }, 800); // Simulate network delay
    });
  };

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    setError(null);
    try {
      await mockApiCall(email, password);
      setUser({ id: '1', email });
    } catch (err: any) {
      setError(err.message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const signup = async (email: string, password: string) => {
    setIsLoading(true);
    setError(null);
    try {
      await mockApiCall(email, password);
      setUser({ id: '2', email });
    } catch (err: any) {
      setError(err.message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    setUser(null);
    setError(null);
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, error, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
}