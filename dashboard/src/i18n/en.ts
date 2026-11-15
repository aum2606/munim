// English catalogue. All user-facing strings live here so other languages can be added later.
export const en = {
  'app.name': 'Munim',
  'common.loading': 'Loading…',
  'common.signOut': 'Sign out',
  'login.title': 'Sign in',
  'login.email': 'Email',
  'login.password': 'Password',
  'login.submit': 'Sign in',
  'login.noAccount': 'New here?',
  'login.createAccount': 'Create your business account',
  'register.title': 'Create your account',
  'register.businessName': 'Business name',
  'register.businessType': 'Type of business (e.g. printing press)',
  'register.yourName': 'Your name',
  'register.passwordHint': 'At least 10 characters',
  'register.submit': 'Create account',
  'register.haveAccount': 'Already registered?',
  'register.signIn': 'Sign in',
  'home.welcome': 'Welcome, {name}',
  'home.workspace': '{business} · {role}',
  'home.next': 'Your catalogue, inbox and quotes will appear here as they are built.',
  'error.generic': 'Something went wrong. Please try again.',
  'error.invalidCredentials': 'Invalid email or password.',
} as const

export type MessageKey = keyof typeof en

export function t(key: MessageKey, vars: Record<string, string> = {}): string {
  return Object.entries(vars).reduce<string>((text, [k, v]) => text.replace(`{${k}}`, v), en[key])
}
