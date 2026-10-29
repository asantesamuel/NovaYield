import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/layout';
import SignUp from './pages/SignUp';
import Login from './pages/Login';
import FieldSetup from './pages/FieldSetup';
import Comparison from './pages/Comparison';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/field" replace />} />
          <Route path="/signup" element={<SignUp />} />
          <Route path="/login" element={<Login />} />
          <Route path="/field" element={<FieldSetup />} />
          <Route path="/comparison" element={<Comparison />} />
          <Route path="*" element={<Navigate to="/field" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}