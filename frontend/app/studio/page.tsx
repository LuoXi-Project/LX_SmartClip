import { Suspense } from 'react'
import StudioPageClient from './StudioPageClient'

export default function Page() {
  return <Suspense fallback={null}><StudioPageClient /></Suspense>
}
