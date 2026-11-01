import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Welcome from './pages/Welcome'
import Interview from './pages/Interview'
import Database from './pages/Database'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Welcome />} />
        <Route path="/interview" element={<Interview />} />
        <Route path="/database" element={<Database />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}