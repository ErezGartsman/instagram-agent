import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'

// globals:false in vitest.config.ts means RTL's auto-cleanup (which hooks a
// global afterEach) never registers itself — wire it explicitly instead, or
// every render() across a file's tests piles up in the same jsdom document.
afterEach(cleanup)
