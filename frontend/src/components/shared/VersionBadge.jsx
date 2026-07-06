/**
 * Small badge showing the running deployment's branch + commit (parsed from
 * the CI image tag by the Helm chart and served by /api/version). Fetched once
 * per session (react-query dedupes by queryKey across mounts). Tooltip carries
 * the full image tag, chart version and environment for debugging.
 */
import { useQuery } from '@tanstack/react-query'
import { Tag } from 'lucide-react'
import { getVersion } from '../../services/api'

const VersionBadge = () => {
  const { data } = useQuery({
    queryKey: ['version'],
    queryFn: getVersion,
    staleTime: Infinity,
    retry: false,
  })

  if (!data) return null

  const label = (data.branch && data.commit)
    ? `${data.branch} @ ${data.commit}`
    : data.image_tag || data.version

  if (!label) return null

  const title = [
    data.image_tag,
    data.chart_version && `chart ${data.chart_version}`,
    data.environment,
  ].filter(Boolean).join(' • ')

  return (
    <span
      title={title}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-mono text-gray-500 bg-gray-50 border border-gray-200 rounded-md"
    >
      <Tag className="w-3 h-3" />
      {label}
    </span>
  )
}

export default VersionBadge
