/**
 * Shared EmptyState component for consistent empty states across pages
 */

import { Link } from 'react-router-dom'

const EmptyState = ({ icon: Icon, title, description, actionLabel, actionTo, onClick }) => (
  <div className="text-center py-16">
    {Icon && (
      <div className="w-14 h-14 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-4">
        <Icon className="w-7 h-7 text-gray-400" />
      </div>
    )}
    <h3 className="text-base font-medium text-gray-900 mb-1">{title}</h3>
    {description && <p className="text-sm text-gray-500 mb-4 max-w-sm mx-auto">{description}</p>}
    {actionLabel && actionTo && (
      <Link
        to={actionTo}
        className="inline-flex items-center px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
      >
        {actionLabel}
      </Link>
    )}
    {actionLabel && onClick && (
      <button
        onClick={onClick}
        className="inline-flex items-center px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
      >
        {actionLabel}
      </button>
    )}
  </div>
)

export default EmptyState
