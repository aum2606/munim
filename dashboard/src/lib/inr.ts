const rupees = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })

/** Display only (lakh grouping, e.g. ₹1,23,456.78). Prices are stored and computed as integer
 * paise on the server; the dashboard never does arithmetic on them. */
export function formatInr(paise: number): string {
  return rupees.format(paise / 100)
}
