/**
 * Split 'use client' page.tsx into server page.tsx + *PageClient.tsx
 * so Next.js params/searchParams are not injected into client page exports.
 */
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const appDir = path.join(__dirname, '..', 'app')

const SEARCH_PARAMS_PAGES = new Set(['process', 'studio'])

function walk(dir, acc = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name)
    if (ent.isDirectory()) walk(p, acc)
    else if (ent.name === 'page.tsx') acc.push(p)
  }
  return acc
}

function clientName(routeDir) {
  const base = path.basename(routeDir)
  if (base === 'app') return 'HomePageClient'
  const camel = base.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
  return camel.charAt(0).toUpperCase() + camel.slice(1) + 'PageClient'
}

for (const pagePath of walk(appDir)) {
  const raw = fs.readFileSync(pagePath, 'utf8')
  if (!raw.startsWith("'use client'") && !raw.startsWith('"use client"')) continue

  const routeDir = path.dirname(pagePath)
  const clientFile = clientName(routeDir) + '.tsx'
  const clientPath = path.join(routeDir, clientFile)
  const routeKey = routeDir === appDir ? '' : path.basename(routeDir)
  const importName = clientFile.replace(/\.tsx$/, '')
  const needsSuspense = SEARCH_PARAMS_PAGES.has(routeKey)

  if (fs.existsSync(clientPath)) {
    console.log('skip (exists):', clientPath)
    continue
  }

  const clientBody = raw.replace(/^['"]use client['"]\s*\n+/, '')
  fs.writeFileSync(clientPath, `'use client'\n\n${clientBody}`, 'utf8')

  const suspenseImport = needsSuspense ? "import { Suspense } from 'react'\n" : ''
  const wrapper = needsSuspense
    ? `<Suspense fallback={null}><${importName} /></Suspense>`
    : `<${importName} />`

  const serverPage = `${suspenseImport}import ${importName} from './${importName}'

export default function Page() {
  return ${wrapper}
}
`
  fs.writeFileSync(pagePath, serverPage, 'utf8')
  console.log('split:', pagePath, '->', clientFile)
}
