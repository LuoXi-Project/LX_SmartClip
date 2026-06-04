import { Suspense } from 'react'
import ProcessPageClient from './ProcessPageClient'

export default function Page() {
  return <Suspense fallback={null}><ProcessPageClient /></Suspense>
}
