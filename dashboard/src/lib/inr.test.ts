import { describe, expect, it } from 'vitest'

import { formatInr, paiseToRupees, rupeesToPaise } from './inr'

describe('rupeesToPaise', () => {
  it('converts typed rupees to integer paise without floating point', () => {
    expect(rupeesToPaise('450')).toBe(45000)
    expect(rupeesToPaise('1,250.5')).toBe(125050)
    expect(rupeesToPaise('0.07')).toBe(7)
    expect(rupeesToPaise(' 235.00 ')).toBe(23500)
    // 19.99 * 100 is 1998.9999999999998 in floating point; this must not leak through
    expect(rupeesToPaise('19.99')).toBe(1999)
    expect(rupeesToPaise('1.1')).toBe(110)
  })

  it('rejects anything that is not a plain amount', () => {
    for (const bad of ['', 'abc', '-5', '1.234', '1e3', '₹100', '12.', '.5', '1234567890']) {
      expect(rupeesToPaise(bad)).toBeNull()
    }
  })
})

describe('display helpers', () => {
  it('round-trips paise through the edit box text', () => {
    for (const paise of [0, 5, 99, 100, 23500, 123456789]) {
      expect(rupeesToPaise(paiseToRupees(paise))).toBe(paise)
    }
    expect(paiseToRupees(23500)).toBe('235.00')
  })

  it('formats with lakh grouping', () => {
    expect(formatInr(12345678)).toBe('₹1,23,456.78')
  })
})
