import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

import { setAccessToken } from '../api/client'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  setAccessToken(null)
})
