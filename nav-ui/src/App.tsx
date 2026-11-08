import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Welcome from './pages/Welcome'
import Interview from './pages/Interview'
import { PrivacyProvider } from './privacy/PrivacyContext'
import { LockButton } from './privacy/LockButton'
import { LockOverlay } from './privacy/LockOverlay'

export default function App() {
  return (
    <BrowserRouter>
      <PrivacyProvider>
        <LockButton />
        <LockOverlay />
        <Routes>
          <Route path="/" element={<Welcome />} />
          <Route path="/interview" element={<Interview />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </PrivacyProvider>
    </BrowserRouter>
  )
}