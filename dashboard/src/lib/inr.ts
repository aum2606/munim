const rupees = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })

/** Display only (lakh grouping, e.g. ₹1,23,456.78). Prices are stored and computed as integer
 * paise on the server; the dashboard never does arithmetic on them. */
export function formatInr(paise: number): string {
  return rupees.format(paise / 100)
}

/** Rupees typed by a person ("450", "1,250.5") to integer paise, without floating point.
 * Returns null for anything that is not a plain amount with at most two decimals. */
export function rupeesToPaise(text: string): number | null {
  const match = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(text.replace(/[,\s]/g, ''))
  if (!match) return null
  const whole = Number(match[1])
  const fraction = Number((match[2] ?? '').padEnd(2, '0'))
  return whole * 100 + fraction
}

/** Integer paise to the plain text shown in an edit box, e.g. 23500 -> "235.00". */
export function paiseToRupees(paise: number): string {
  const rupees = Math.floor(paise / 100)
  return `${rupees}.${String(paise % 100).padStart(2, '0')}`
}
