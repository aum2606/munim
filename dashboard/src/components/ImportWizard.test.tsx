import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'

import type { ImportPreview } from '../api/knowledge'
import { mockApi, renderAt } from '../test/helpers'
import { ImportWizard } from './ImportWizard'

const PREVIEW: ImportPreview = {
  job_id: 'job-1',
  filename: 'prices.xlsx',
  status: 'previewed',
  headers: ['Item', 'Rate'],
  mapping: { name: 'Item', price: 'Rate' },
  missing_required: [],
  row_count: 3,
  valid_count: 2,
  error_count: 1,
  rows: [
    { row: 3, values: {}, errors: ["price 'about 300' is not a valid amount"] },
    { row: 2, values: {}, errors: [] },
  ],
}

it('uploads a file, shows the problem rows, and saves only after confirmation', async () => {
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/catalog/import' && init?.method === 'POST') {
      return { status: 201, body: PREVIEW }
    }
    if (url === '/api/v1/catalog/import/job-1/commit') {
      return { status: 200, body: { created: 2, updated: 0, skipped: 1 } }
    }
  })
  renderAt(<ImportWizard onClose={() => undefined} />)

  const file = new File(['sku,name,price'], 'prices.csv', { type: 'text/csv' })
  await userEvent.upload(screen.getByLabelText('Choose an Excel or CSV file'), file)
  await userEvent.click(screen.getByRole('button', { name: 'Upload and preview' }))

  expect(await screen.findByText(/2 of 3 rows are ready/)).toBeInTheDocument()
  expect(screen.getByText(/Row 3: price 'about 300'/)).toBeInTheDocument()

  // the file went up as multipart form data, with no JSON content type forced on it
  const upload = fetchMock.mock.calls[0]?.[1]
  expect(upload?.body).toBeInstanceOf(FormData)
  expect(upload?.headers).not.toHaveProperty('Content-Type')
  expect(fetchMock).toHaveBeenCalledTimes(1) // nothing is saved yet

  await userEvent.click(screen.getByRole('button', { name: 'Save 2 items' }))
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Saved. 2 added, 0 updated, 1 skipped.',
  )
})

it('lets the owner fix the column mapping and re-checks the rows', async () => {
  const broken = { ...PREVIEW, mapping: {}, missing_required: ['name', 'price'], valid_count: 0 }
  const fetchMock = mockApi((url, init) => {
    if (url === '/api/v1/catalog/import') return { status: 201, body: broken }
    if (url === '/api/v1/catalog/import/job-1' && init?.method === 'PATCH') {
      return { status: 200, body: PREVIEW }
    }
  })
  renderAt(<ImportWizard onClose={() => undefined} />)
  await userEvent.upload(
    screen.getByLabelText('Choose an Excel or CSV file'),
    new File(['x'], 'p.csv', { type: 'text/csv' }),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Upload and preview' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Choose a column for: name, price')
  expect(screen.getByRole('button', { name: /Save 0 items/ })).toBeDisabled()

  await userEvent.selectOptions(screen.getByLabelText('name'), 'Item')
  await screen.findByText(/2 of 3 rows are ready/)
  const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
  expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ mapping: { name: 'Item' } })
})

it('shows the server error when the upload is rejected', async () => {
  mockApi(() => ({
    status: 422,
    body: { error: { code: 'file_rejected', message: 'Upload an Excel (.xlsx) or CSV file' } },
  }))
  renderAt(<ImportWizard onClose={() => undefined} />)
  await userEvent.upload(
    screen.getByLabelText('Choose an Excel or CSV file'),
    new File(['x'], 'p.csv', { type: 'text/csv' }),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Upload and preview' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Upload an Excel (.xlsx) or CSV file')
})
