import { server } from './server'

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  localStorage.clear()
})
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
