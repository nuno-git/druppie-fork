import { Link } from 'react-router-dom'

const EmptyState = ({ icon: Icon, title, description, actionLabel, actionTo, onClick }) => (
  <div className="text-center py-12">
    {Icon && (
      <div className="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center mx-auto mb-3">
        <Icon className="w-6 h-6 text-gray-400" />
      </div>
    )}
    <h3 className="text-sm font-semibold text-gray-900 mb-0.5">{title}</h3>
    {description && <p className="text-sm text-gray-500 mb-4 max-w-xs mx-auto">{description}</p>}
    {actionLabel && actionTo && (
      <Link
        to={actionTo}
        className="inline-flex items-center px-3.5 py-1.5 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
      >
        {actionLabel}
      </Link>
    )}
    {actionLabel && onClick && (
      <button
        onClick={onClick}
        className="inline-flex items-center px-3.5 py-1.5 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
      >
        {actionLabel}
      </button>
    )}
  </div>
)

export default EmptyState
