/**
 * Skeleton loading components for consistent loading states
 */

const Pulse = ({ className = '' }) => (
  <div className={`animate-pulse bg-gray-200 rounded ${className}`} />
)

export const SkeletonLine = ({ width = 'w-full', height = 'h-4' }) => (
  <Pulse className={`${width} ${height}`} />
)

export const SkeletonStatCard = () => (
  <div className="bg-white rounded-xl border border-gray-100 p-6">
    <div className="flex items-center justify-between">
      <div className="space-y-3 flex-1">
        <Pulse className="h-3 w-20" />
        <Pulse className="h-8 w-16" />
      </div>
      <Pulse className="w-10 h-10 rounded-lg" />
    </div>
  </div>
)

export const SkeletonCard = ({ lines = 3 }) => (
  <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-3">
    <Pulse className="h-5 w-3/5" />
    {Array.from({ length: lines }).map((_, i) => (
      <Pulse key={i} className={`h-3 ${i === lines - 1 ? 'w-2/5' : 'w-full'}`} />
    ))}
  </div>
)

export const SkeletonProjectCard = () => (
  <div className="bg-white rounded-xl border border-gray-100 p-4 space-y-3">
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Pulse className="w-5 h-5 rounded" />
        <Pulse className="h-5 w-32" />
      </div>
      <Pulse className="h-5 w-16 rounded-full" />
    </div>
    <Pulse className="h-3 w-full" />
    <Pulse className="h-10 w-full rounded-lg" />
    <div className="flex items-center justify-between">
      <Pulse className="h-3 w-20" />
      <Pulse className="h-3 w-16" />
    </div>
    <Pulse className="h-9 w-full rounded-lg" />
  </div>
)

export const SkeletonListItem = () => (
  <div className="flex items-center justify-between p-3 rounded-lg">
    <div className="space-y-2 flex-1">
      <Pulse className="h-4 w-2/5" />
      <Pulse className="h-3 w-1/4" />
    </div>
    <Pulse className="h-5 w-16 rounded-full" />
  </div>
)

export const SkeletonTaskCard = () => (
  <div className="bg-white rounded-xl border border-gray-100 p-4 space-y-3">
    <div className="flex items-start justify-between">
      <div className="space-y-2 flex-1">
        <div className="flex items-center gap-2">
          <Pulse className="w-4 h-4 rounded" />
          <Pulse className="h-5 w-40" />
        </div>
        <Pulse className="h-3 w-3/4" />
      </div>
      <div className="flex gap-2">
        <Pulse className="h-8 w-20 rounded-lg" />
        <Pulse className="h-8 w-16 rounded-lg" />
      </div>
    </div>
  </div>
)

export const SkeletonSidebarItem = () => (
  <div className="px-4 py-2.5 space-y-2">
    <Pulse className="h-4 w-3/4" />
    <div className="flex items-center gap-2">
      <Pulse className="h-3 w-16" />
      <Pulse className="h-3 w-12 ml-auto" />
    </div>
  </div>
)

export const SkeletonSettingsSection = () => (
  <div className="bg-white rounded-xl border border-gray-100 p-6 space-y-4">
    <div className="flex items-center gap-2 mb-4">
      <Pulse className="w-4 h-4 rounded" />
      <Pulse className="h-3 w-24" />
    </div>
    {Array.from({ length: 3 }).map((_, i) => (
      <div key={i} className="flex items-center gap-3 px-3 py-2.5">
        <Pulse className="w-2 h-2 rounded-full" />
        <Pulse className="h-4 w-32" />
        <Pulse className="h-3 w-16 ml-auto" />
      </div>
    ))}
  </div>
)
